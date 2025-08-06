import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Mapping, NewType, Optional, Set

from flask import Blueprint, abort, json, jsonify, request
from models import Reply, Source, Submission
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Query, joinedload
from sqlalchemy.orm.exc import MultipleResultsFound
from werkzeug.wrappers.response import Response

blp = Blueprint("api2", __name__, url_prefix="/api/v2")

PREFIX_MAX_LEN = inspect(Source).columns["uuid"].type.length


def all_sources() -> Query:
    """
    Return a base query for all ``Sources`` with eager loading of their metadata
    and collections.
    """
    return (
        Source.query.options(joinedload(Source.star))
        .options(joinedload(Source.submissions))
        .options(joinedload(Source.replies))
    )


Version = NewType("Version", str)


def json_version(d: Mapping) -> Version:
    """
    Calculate the version (BLAKE2s digest) of the normalized JSON representation
    of the dictionary ``d``.

    We use BLAKE2s here because SHA-256 is too slow (we don't care about
    cryptographic security) and CRC-32 is too collision-prone (we're not merely
    checksumming for transmission integrity).
    """
    s = json.dumps(d, separators=[",", ":"], sort_keys=True)
    b = s.encode("utf-8")
    return Version(hashlib.blake2s(b).hexdigest())


# TODO: generic UUID[T] in Python 3.12
SourceUUID = NewType("SourceUUID", str)
ItemUUID = NewType("ItemUUID", str)


@dataclass
class Index:
    sources: Dict[SourceUUID, Version] = field(default_factory=dict)
    items: Dict[ItemUUID, Version] = field(default_factory=dict)


@blp.get("/index")
@blp.get("/index/<string:prefix>")
def index(prefix: Optional[str] = None) -> Response:
    """
    By default, return the ETag-versioned ``Index`` of all sources and their
    items, unless the client provides the ETag of the current index.

    Given a ``prefix``, return the sub-index of all sources whose UUIDs begin
    with that prefix (and their items), unless the client provides the ETag of
    the current sub-index for that prefix.  The client MAY choose an arbitrary
    prefix with each request: e.g., a series of requests with the prefixes
    ``{0...f}`` will effectively shard the index into 16 shards.
    """
    index = Index()

    query = all_sources()
    if prefix is not None:
        if len(prefix) >= PREFIX_MAX_LEN:
            abort(
                422, f"malformed request; prefix must be shorter than {PREFIX_MAX_LEN} characters"
            )

        query = query.filter(Source.uuid.startswith(prefix))

    for source in query.all():
        all_source_metadata = source.to_api_v2()
        index.sources[source.uuid] = json_version(all_source_metadata)
        for uuid, item in all_source_metadata["collection"].items():
            index.items[uuid] = json_version(item)

    version = json_version(asdict(index))
    response = jsonify(asdict(index))

    # If the request's `If-None-Match` header matches the version,
    # return HTTP 304 with an empty response.
    response.set_etag(version)
    return response.make_conditional(request)


@dataclass
class MetadataRequest:
    sources: Set[SourceUUID] = field(default_factory=set)
    items: Set[ItemUUID] = field(default_factory=set)


@dataclass
class MetadataResponse:
    sources: Dict[SourceUUID, Any] = field(default_factory=dict)
    items: Dict[ItemUUID, Any] = field(default_factory=dict)


@blp.post("/metadata")
def metadata() -> Response:
    """
    Return the ``MetadataResponse`` requested in the ``MetadataRequest``.  The
    client MAY choose an arbitrary list of sources and items with each request,
    e.g. from a shard retrieved from ``/index/<prefix>``.

    NB.  Returning sources is O(1) from the eagerly-loaded ``all_sources()``.
    Returning items is O(2), since we have to search both the ``Submission`` and
    the ``Reply`` tables for the set of all item UUIDs.
    """
    try:
        requested = MetadataRequest(**request.json)  # type: ignore
    except (TypeError, ValueError) as exc:
        abort(422, f"malformed request; {exc}")

    response = MetadataResponse()

    for source in all_sources().filter(Source.uuid.in_(str(uuid) for uuid in requested.sources)):
        response.sources[source.uuid] = source.to_api_v2()

    for item in Submission.query.filter(Submission.uuid.in_(str(uuid) for uuid in requested.items)):
        response.items[item.uuid] = item.to_api_v2()

    for item in Reply.query.filter(Reply.uuid.in_(str(uuid) for uuid in requested.items)):
        if item.uuid in response.items:
            # Fail if we get unlucky and hit a UUID collision between the
            # `Submission` and `Reply` tables.  This is vanishingly unlikely,
            # but SQLite can't enforce uniqueness between them.
            raise MultipleResultsFound(f"found {item.uuid} in both submissions and replies")
        response.items[item.uuid] = item.to_api_v2()

    return jsonify(asdict(response))
