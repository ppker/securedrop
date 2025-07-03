import hashlib
from typing import Any, Dict

from flask import Blueprint, abort, json, jsonify, request
from models import Source
from sqlalchemy.orm import joinedload
from werkzeug.wrappers.response import Response

blp = Blueprint("api2", __name__, url_prefix="/api/v2")


def json_version(d: dict) -> str:
    """
    Calculate the version (BLAKE2s digest) of the normalized JSON representation
    of the dictionary ``d``.

    We use BLAKE2s here because SHA-256 is too slow (we don't care about
    cryptographic security) and CRC-32 is too collision-prone (we're not merely
    checksumming for transmission integrity).
    """
    s = json.dumps(d, sort_keys=True)
    b = s.encode("utf-8")
    return hashlib.blake2s(b).hexdigest()


@blp.get("/index")
def index() -> Response:
    """
    Return the index of all sources.

    If the request's ``If-None-Match`` header matches the current ETag, this
    view MUST return HTTP 304 with an empty response.
    """
    sources = {}
    for source in (
        Source.query.options(joinedload(Source.star))
        .options(joinedload(Source.submissions))
        .options(joinedload(Source.replies))
        .all()
    ):
        all_source_metadata = source.to_api_v2()
        source_info: Dict[str, Any] = {
            "version": json_version(all_source_metadata["source"]),
            "collection": {},
        }
        for uuid, item in all_source_metadata["collection"].items():
            source_info["collection"][uuid] = json_version(item)
        sources[source.uuid] = source_info

    index = {"sources": sources}
    version = json_version(index)
    response = jsonify(index)
    response.set_etag(version)
    return response.make_conditional(request)


@blp.get("/index/<string:prefix>")
def index_prefix(prefix: str) -> Response:
    """
    OPTIONAL: Return the index of all sources whose UUIDs begin with
    ``prefix``.  The client MAY choose an arbitrary prefix with each
    request: e.g., a series of requests with the prefixes ``{0...f}`` will
    effectively shard the index into 16 shards.

    If the request's ``If-None-Match`` header matches the current ETag, this
    view MUST return HTTP 304 with an empty response.
    """
    sources = {}
    for source in (
        Source.query.options(joinedload(Source.star))
        .options(joinedload(Source.submissions))
        .options(joinedload(Source.replies))
        .filter(Source.uuid.startswith(prefix))
        .all()
    ):
        all_source_metadata = source.to_api_v2()
        source_info: Dict[str, Any] = {
            "version": json_version(all_source_metadata["source"]),
            "collection": {},
        }
        for uuid, item in all_source_metadata["collection"].items():
            source_info["collection"][uuid] = json_version(item)
        sources[source.uuid] = source_info

    index = {"sources": sources}
    version = json_version(index)
    response = jsonify(index)
    response.set_etag(version)
    return response.make_conditional(request)


@blp.post("/sources")
def sources() -> Response:
    """
    Return the source metadata for the sources listed in the source delta.
    The client MAY choose an arbitrary source delta with each request, e.g.
    from a shard retrieved from ``/index/<prefix>``.
    """
    # Parse and validate the request body
    try:
        requested = json.loads(request.data.decode())
    except ValueError:
        abort(400, "malformed request; invalid JSON")
    if not isinstance(requested, dict):
        abort(400, "malformed request")
    if (
        "full_sources" not in requested
        or not isinstance(requested["full_sources"], list)
        or not all(isinstance(item, str) for item in requested["full_sources"])
    ):
        abort(400, "malformed request; full_sources must be a list of strings")
    if "partial_sources" not in requested or not isinstance(requested["partial_sources"], dict):
        abort(400, "malformed request; partial_sources must be a dict")
    for value in requested["partial_sources"].values():
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            abort(400, "malformed request; each value in partial_sources must be a list of strings")

    # All the sources we need to look up
    source_lookup = set(requested["full_sources"]) | set(requested["partial_sources"].keys())
    response: Dict[str, Dict[str, Any]] = {"sources": {}}
    for source in (
        Source.query.options(joinedload(Source.star))
        .options(joinedload(Source.submissions))
        .options(joinedload(Source.replies))
        .filter(Source.uuid.in_(str(uuid) for uuid in source_lookup))
    ):
        all_source_metadata = source.to_api_v2()
        source_info: Dict[str, Any] = {"collection": {}}
        want_full = source.uuid in requested["full_sources"]
        if want_full:
            source_info["info"] = all_source_metadata["source"]
        partial = requested["partial_sources"].get(source.uuid, [])
        for uuid, item in all_source_metadata["collection"].items():
            if want_full or uuid in partial:
                source_info["collection"][uuid] = item
        response["sources"][source.uuid] = source_info
    return jsonify(response)
