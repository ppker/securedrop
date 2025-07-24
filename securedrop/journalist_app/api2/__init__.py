import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, NewType, Optional

from flask import Blueprint, abort, json, jsonify, request
from models import Source
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Query, joinedload
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
class IndexSourceEntry:
    version: Version
    collection: Dict[ItemUUID, Version] = field(default_factory=dict)


@dataclass
class Index:
    sources: Dict[SourceUUID, IndexSourceEntry] = field(default_factory=dict)


@blp.get("/index")
@blp.get("/index/<string:prefix>")
def index(prefix: Optional[str] = None) -> Response:
    """
    By default, return the ETag-versioned ``Index`` consisting of an
    ``IndexSourceEntry`` for each source and its collection, unless the client
    provides the ETag of the current index.

    Given a ``prefix``, return the sub-index of all sources whose UUIDs begin
    with that prefix, unless the client provides the ETag of the current
    sub-index for that prefix.  The client MAY choose an arbitrary prefix with
    each request: e.g., a series of requests with the prefixes ``{0...f}`` will
    effectively shard the index into 16 shards.
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
        source_entry = IndexSourceEntry(
            version=json_version(all_source_metadata["source"]),
        )
        for uuid, item in all_source_metadata["collection"].items():
            source_entry.collection[uuid] = json_version(item)
        index.sources[source.uuid] = source_entry

    version = json_version(asdict(index))
    response = jsonify(asdict(index))

    # If the request's `If-None-Match` header matches the version,
    # return HTTP 304 with an empty response.
    response.set_etag(version)
    return response.make_conditional(request)


@dataclass
class SourcesRequest:
    full_sources: List[SourceUUID] = field(default_factory=list)
    partial_sources: Mapping[SourceUUID, List[ItemUUID]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.full_sources, list):
            raise ValueError("full_sources must be a list of strings")
        if not all(isinstance(item, str) for item in self.full_sources):
            raise ValueError("full_sources must be a list of strings")

        if not isinstance(self.partial_sources, Mapping):
            raise ValueError("partial_sources must be a dict")
        for key, value in self.partial_sources.items():
            if not isinstance(key, str):
                raise ValueError("partial_sources must be keyed by UUID")
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError("each value in partial_sources must be a list of strings")


@dataclass
class SourceEntry:
    collection: Dict[ItemUUID, Any] = field(default_factory=dict)


@dataclass
class FullSourceEntry(SourceEntry):
    info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SourcesResponse:
    sources: Dict[SourceUUID, SourceEntry] = field(default_factory=dict)


@blp.post("/sources")
def sources() -> Response:
    """
    Return the ``SourcesResponse`` requested in the ``SourcesRequest``.  For "full"
    sources, return all metadata.  For "partial" sources, return metadata only
    for the specified items in their collections.

    The client MAY choose an arbitrary source delta with each request, e.g.
    from a shard retrieved from ``/index/<prefix>``.
    """
    try:
        requested = SourcesRequest(**request.json)  # type: ignore
    except (TypeError, ValueError) as exc:
        abort(422, f"malformed request; {exc}")

    # Look up all requested sources, and return both "full" and "partial"
    # metadata in a single pass.
    source_lookup = set(requested.full_sources) | set(requested.partial_sources.keys())
    response = SourcesResponse()

    for source in all_sources().filter(Source.uuid.in_(str(uuid) for uuid in source_lookup)):
        all_source_metadata = source.to_api_v2()
        want_full = source.uuid in requested.full_sources
        partial = requested.partial_sources.get(source.uuid, [])
        cls = FullSourceEntry if want_full else SourceEntry
        source_entry = cls()
        for uuid, item in all_source_metadata["collection"].items():
            if want_full or uuid in partial:
                source_entry.collection[uuid] = item
        if want_full:
            source_entry.info = all_source_metadata["source"]
        response.sources[source.uuid] = source_entry

    return jsonify(asdict(response))
