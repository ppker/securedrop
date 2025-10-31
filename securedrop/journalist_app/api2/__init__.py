from dataclasses import asdict
from typing import Optional

from flask import Blueprint, abort, jsonify, request
from journalist_app.api2.events import EventHandler
from journalist_app.api2.shared import json_version
from journalist_app.api2.types import (
    BatchRequest,
    BatchResponse,
    Event,
    Index,
)
from journalist_app.sessions import session
from models import EagerQuery, Journalist, Reply, Source, Submission, eager_query
from redis import Redis
from sdconfig import SecureDropConfig
from sqlalchemy.inspection import inspect
from sqlalchemy.orm.exc import MultipleResultsFound
from werkzeug.wrappers.response import Response

blp = Blueprint("api2", __name__, url_prefix="/api/v2")

EVENTS_MAX = 50
PREFIX_MAX_LEN = inspect(Source).columns["uuid"].type.length


# Magic numbers to avoid having to define an `IntEnum` somewhere that can be
# imported from `securedrop.models`:
#
# 0. Initial implementation
# 1. `Index` and `BatchResponse` include `journalists`
# 2. `Reply` and `Submission` objects include `interaction_count`
# 3. `BatchRequest` accepts `events` to process, with results returned in
#    `BatchResponse.events`
API_MINOR_VERSION = 3  # 2.x


def get_request_minor_version() -> int:
    try:
        prefer = request.headers.get("Prefer", f"securedrop={API_MINOR_VERSION}")
        minor_version = int(prefer.split("=")[1])
        if 0 <= minor_version <= API_MINOR_VERSION:
            return minor_version
        else:
            return API_MINOR_VERSION
    except (IndexError, ValueError):
        return API_MINOR_VERSION


@blp.get("/index")
@blp.get("/index/<string:source_prefix>")
def index(source_prefix: Optional[str] = None) -> Response:
    """
    By default, return the ETag-versioned ``Index`` of all metadata unless the
    client provides the ETag of the current index.

    Given a ``source_prefix``, return the sub-index of source metadata for all
    sources whose UUIDs begin with that prefix, plus all non-source metadata,
    unless the client provides the ETag of the current sub-index for that
    prefix.  The client MAY choose an arbitrary prefix with each request: e.g.,
    a series of requests with the prefixes ``{0...f}`` will effectively shard
    the source index into 16 shards.  (Non-source metadata is not filtered by
    the prefix and is always returned.)
    """
    minor = get_request_minor_version()
    index = Index()

    source_query: EagerQuery = eager_query("Source")
    if source_prefix is not None:
        if len(source_prefix) >= PREFIX_MAX_LEN:
            abort(
                422,
                f"malformed request; source prefix must be shorter than {PREFIX_MAX_LEN} "
                f"characters",
            )

        source_query = source_query.filter(Source.uuid.startswith(source_prefix))

    for source in source_query.all():
        index.sources[source.uuid] = json_version(source.to_api_v2(minor))
        for item in source.collection:
            index.items[item.uuid] = json_version(item.to_api_v2(minor))

    journalist_query: EagerQuery = eager_query("Journalist")
    for journalist in journalist_query.all():
        index.journalists[journalist.uuid] = json_version(journalist.to_api_v2(minor))

    # We want to enforce the *current* shape of `Index`, so we should wait until
    # we have the dictionary representation to delete top-level keys unsupported
    # by the current minor version.
    index_dict = asdict(index)
    if minor < 1:
        del index_dict["journalists"]

    version = json_version(index_dict)
    response = jsonify(index_dict)

    # If the request's `If-None-Match` header matches the version,
    # return HTTP 304 with an empty response.
    response.set_etag(version)
    return response.make_conditional(request)


@blp.post("/data")  # read-write BatchRequest
@blp.post("/metadata")  # DEPRECATED: read-only MetadataRequest
def data() -> Response:
    """
    Return the ``BatchResponse`` requested in the ``BatchRequest``.  The
    client MAY choose an arbitrary list of objects with each request, e.g. from
    a shard retrieved from ``/index/<source_prefix>``.

    The client MAY include a list of ``Event``s for the server to process over
    arbitrary sources and items.  Ordering is guaranteed within a given
    ``BatchRequest``.  Sources and items changed by one or more events will be
    returned in their most-recent state in the ``BatchResponse`` whether or not
    they were explicitly requested in the ``BatchRequest``.

    NB.  Reading sources (without any side effects from processing events) is
    O(1) from the eagerly-loaded ``all_sources()``.  Reading items is O(2),
    since we have to search both the ``Submission`` and the ``Reply`` tables for
    the set of all item UUIDs.
    """
    try:
        requested = BatchRequest(**request.json)  # type: ignore
    except (TypeError, ValueError) as exc:
        abort(422, f"malformed request; {exc}")

    minor = get_request_minor_version()
    response = BatchResponse()

    if minor < 3 and requested.events:
        abort(400, "Events are not supported for API minor version < 3")
    if minor >= 3 and requested.events:
        if len(requested.events) > EVENTS_MAX:
            abort(429, f"a BatchRequest MUST NOT include more than {EVENTS_MAX} events")

        try:
            events = [Event(**d) for d in requested.events]
        except (TypeError, ValueError) as e:
            abort(400, f"invalid event: {e}")

        # Don't set up the EventHandler, connect to Redis, etc., unless we have
        # events to process.
        config = SecureDropConfig.get_current()
        handler = EventHandler(
            session=session, redis=Redis(decode_responses=True, **config.REDIS_KWARGS)
        )

        # Process events in snowflake order.
        for event in sorted(events, key=lambda e: int(e.id)):
            result = handler.process(event, minor)
            for uuid, source in result.sources.items():
                response.sources[uuid] = source.to_api_v2(minor) if source is not None else None
            for uuid, item in result.items.items():
                response.items[uuid] = item.to_api_v2(minor) if item is not None else None
            response.events[result.event_id] = result.status

    # The set of items (UUIDs) that were emitted by processed events.
    items_emitted = frozenset(response.items.keys())

    if requested.sources:
        source_query: EagerQuery = eager_query("Source")
        for source in source_query.filter(Source.uuid.in_(str(uuid) for uuid in requested.sources)):
            response.sources[source.uuid] = source.to_api_v2(minor)

    if requested.items:
        # If an item was explicitly requested but was already emitted by a
        # processed event, we don't need to (and shouldn't) reread it.
        left_to_read = set(requested.items) - items_emitted

        submission_query: EagerQuery = eager_query("Submission")
        for item in submission_query.filter(
            Submission.uuid.in_(str(uuid) for uuid in left_to_read)
        ):
            response.items[item.uuid] = item.to_api_v2(minor)

        reply_query: EagerQuery = eager_query("Reply")
        for item in reply_query.filter(Reply.uuid.in_(str(uuid) for uuid in left_to_read)):
            if item.uuid in response.items.keys() - items_emitted:
                # Fail if we get unlucky and hit a UUID collision between the
                # `Submission` and `Reply` tables.  This is vanishingly unlikely,
                # but SQLite can't enforce uniqueness between them.
                raise MultipleResultsFound(f"found {item.uuid} in both submissions and replies")
            response.items[item.uuid] = item.to_api_v2(minor)

    if requested.journalists:
        journalist_query: EagerQuery = eager_query("Journalist")
        for journalist in journalist_query.filter(
            Journalist.uuid.in_(str(uuid) for uuid in requested.journalists)
        ):
            response.journalists[journalist.uuid] = journalist.to_api_v2(minor)

    response_dict = asdict(response)

    # We want to enforce the *current* shape of `BatchResponse`, so we should
    # wait until we have the dictionary representation to delete top-level keys
    # unsupported by the current minor version.
    if minor < 1:
        del response_dict["journalists"]
    if minor < 3:
        del response_dict["events"]

    return jsonify(response_dict)
