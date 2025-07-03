from contextlib import contextmanager

import pytest
from flask import url_for
from flask_sqlalchemy import get_debug_queries
from journalist_app.api2 import json_version
from tests.utils.api_helper import get_api_headers


def filtered_queries():
    # filter out PRAGMA, instance_config loading, etc.
    return [
        q
        for q in get_debug_queries()
        if q.statement.startswith("SELECT")
        and not q.statement.startswith("SELECT instance_config.")
    ]


@contextmanager
def assert_query_count(expected_count):
    """verify an API request makes the expected number of queries"""
    initial_count = len(filtered_queries())
    yield
    new_queries = filtered_queries()[initial_count:]
    # If the first API request is to look up journalists, it's part of the login flow, so skip it
    if len(new_queries) >= 1 and new_queries[0].statement.startswith("SELECT journalists."):
        new_queries = new_queries[1:]

    assert (
        len(new_queries) == expected_count
    ), f"Expected {expected_count} queries, but {len(new_queries)} were executed"


def test_json_version():
    d = {"foo": "bar", "baz": "biz"}
    version1 = json_version(d)
    assert version1 == "593ffee39176ea092546a7df8247c9b3936102abf539ed212492d817ccdeb19a"

    d2 = {"baz": "biz", "foo": "bar"}
    version2 = json_version(d2)
    assert version1 == version2


@pytest.mark.parametrize(
    ("endpoint", "kwargs"),
    [
        ("api2.index", {}),
        ("api2.index_prefix", {"prefix": "foo"}),
        # while this should be a POST request, the 403 will kick in first
        ("api2.sources", {}),
    ],
)
def test_auth_required(journalist_app, endpoint, kwargs):
    """
    Verify all APIv2 endpoints require authentication
    """
    with journalist_app.test_client() as app:
        response = app.get(url_for(endpoint, **kwargs))

        assert response.status_code == 403


def test_index(journalist_app, test_files, journalist_api_token):
    """
    Verify GET /index response and HTTP 304 behavior
    """
    with journalist_app.test_client() as app:
        uuid = test_files["source"].uuid
        with assert_query_count(1):
            response = app.get(
                url_for("api2.index"),
                headers=get_api_headers(journalist_api_token),
            )

        # Verify the source is in the response
        assert response.status_code == 200
        assert uuid in response.json["sources"]
        # test_files generates 2 submissions and 1 reply, so 3 items total
        assert len(response.json["sources"][uuid]["collection"]) == 3

        with assert_query_count(1):
            response2 = app.get(
                url_for("api2.index"),
                headers={
                    **get_api_headers(journalist_api_token),
                    "If-None-Match": response.headers["ETag"],
                },
            )

        # With the etag, verify we get a 304
        assert response2.status_code == 304


def test_index_prefix(journalist_app, test_files, journalist_api_token):
    """
    Verify GET /index/<prefix> response and HTTP 304 behavior
    """
    with journalist_app.test_client() as app:
        uuid = test_files["source"].uuid
        with assert_query_count(1):
            response = app.get(
                url_for("api2.index_prefix", prefix=uuid[0]),
                headers=get_api_headers(journalist_api_token),
            )

        # Verify the source is in the response
        assert response.status_code == 200
        assert uuid in response.json["sources"]
        # test_files generates 2 submissions and 1 reply, so 3 items total
        assert len(response.json["sources"][uuid]["collection"]) == 3

        with assert_query_count(1):
            response2 = app.get(
                url_for("api2.index_prefix", prefix=uuid[0]),
                headers={
                    **get_api_headers(journalist_api_token),
                    "If-None-Match": response.headers["ETag"],
                },
            )

        # With the etag, verify we get a 304
        assert response2.status_code == 304

        # Make a response with an invalid prefix ("x")
        response3 = app.get(
            url_for("api2.index_prefix", prefix="x"),
            headers=get_api_headers(journalist_api_token),
        )
        # HTTP 200, but zero sources
        assert response3.status_code == 200
        assert response3.json["sources"] == {}


def test_sources(journalist_app, test_files, journalist_api_token):
    """
    Verify POST /sources response
    """
    with journalist_app.test_client() as app:
        uuid = test_files["source"].uuid
        index = app.get(
            url_for("api2.index"),
            headers=get_api_headers(journalist_api_token),
        )

        assert index.status_code == 200
        source_versions = index.json["sources"][uuid]

        # Get the full source
        with assert_query_count(1):
            response = app.post(
                url_for("api2.sources"),
                json={"full_sources": [uuid], "partial_sources": {}},
                headers=get_api_headers(journalist_api_token),
            )
        assert response.status_code == 200
        assert uuid in response.json["sources"]
        source = response.json["sources"][uuid]
        # Verify the source has the same version
        assert json_version(source["info"]) == source_versions["version"]
        # Verify the collection has an identical set of UUIDs and the versions are the same
        assert set(source["collection"].keys()) == set(source_versions["collection"].keys())
        for item_uuid, item in source["collection"].items():
            assert json_version(item) == source_versions["collection"][item_uuid]

        # Get a partial source
        item_uuid = list(source["collection"].keys())[0]
        with assert_query_count(1):
            response = app.post(
                url_for("api2.sources"),
                json={"full_sources": [], "partial_sources": {uuid: [item_uuid]}},
                headers=get_api_headers(journalist_api_token),
            )
        assert response.status_code == 200
        assert uuid in response.json["sources"]
        source = response.json["sources"][uuid]
        # Verify no source metadata is returned
        assert "info" not in source
        # Verify the collection has an identical set of UUIDs and the versions are the same
        assert set(source["collection"].keys()) == {item_uuid}
        assert (
            json_version(source["collection"][item_uuid])
            == source_versions["collection"][item_uuid]
        )


# Verify POST /sources input validation


@pytest.mark.parametrize(
    ("invalid_data", "expected_error"),
    [
        ("invalid json{", "malformed request; invalid JSON"),
        ("", "malformed request; invalid JSON"),
        # null is technically valid JSON, but still invalid for our purposes
        ("null", "malformed request"),
    ],
)
def test_api2_sources_validation_invalid_json(
    journalist_app, journalist_api_token, invalid_data, expected_error
):
    """Test that invalid JSON returns 400 with appropriate error message."""
    with journalist_app.test_client() as app:
        response = app.post(
            url_for("api2.sources"),
            data=invalid_data,
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 400
        assert expected_error in response.get_data(as_text=True)


@pytest.mark.parametrize(
    "invalid_request",
    [
        ["not", "a", "dict"],
        "string instead of dict",
        123,
        None,
        True,
    ],
)
def test_api2_sources_validation_non_dict_request(
    journalist_app, journalist_api_token, invalid_request
):
    """Test that non-dict request body returns 400."""
    with journalist_app.test_client() as app:
        response = app.post(
            url_for("api2.sources"),
            json=invalid_request,
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 400
        assert "malformed request" in response.get_data(as_text=True)


@pytest.mark.parametrize(
    ("request_body", "expected_error"),
    [
        # Missing full_sources
        ({"partial_sources": {}}, "full_sources must be a list of strings"),
        # full_sources not a list
        (
            {"full_sources": "not a list", "partial_sources": {}},
            "full_sources must be a list of strings",
        ),
        # full_sources with non-string items
        (
            {"full_sources": ["valid", 123, "another"], "partial_sources": {}},
            "full_sources must be a list of strings",
        ),
    ],
)
def test_api2_sources_validation_full_sources_errors(
    journalist_app, journalist_api_token, request_body, expected_error
):
    """Test various full_sources validation errors."""
    with journalist_app.test_client() as app:
        response = app.post(
            url_for("api2.sources"),
            json=request_body,
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 400
        assert expected_error in response.get_data(as_text=True)


@pytest.mark.parametrize(
    ("request_body", "expected_error"),
    [
        # Missing partial_sources
        ({"full_sources": []}, "partial_sources must be a dict"),
        # partial_sources not a dict
        ({"full_sources": [], "partial_sources": "not a dict"}, "partial_sources must be a dict"),
        # partial_sources values not lists
        (
            {"full_sources": [], "partial_sources": {"key1": "not a list"}},
            "each value in partial_sources must be a list of strings",
        ),
        # partial_sources values with non-string items
        (
            {"full_sources": [], "partial_sources": {"key1": ["valid", 123]}},
            "each value in partial_sources must be a list of strings",
        ),
        # Multiple keys, one invalid
        (
            {"full_sources": [], "partial_sources": {"key1": ["valid"], "key2": "not a list"}},
            "each value in partial_sources must be a list of strings",
        ),
    ],
)
def test_api2_sources_validation_partial_sources_errors(
    journalist_app, journalist_api_token, request_body, expected_error
):
    """Test various partial_sources validation errors."""
    with journalist_app.test_client() as app:
        response = app.post(
            url_for("api2.sources"),
            json=request_body,
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 400
        assert expected_error in response.get_data(as_text=True)


@pytest.mark.parametrize(
    "valid_request",
    [
        # Empty but valid
        {"full_sources": [], "partial_sources": {}},
        # Only full_sources
        {"full_sources": ["uuid1", "uuid2"], "partial_sources": {}},
        # Only partial_sources
        {"full_sources": [], "partial_sources": {"key1": ["item1", "item2"]}},
        # Both with data
        {
            "full_sources": ["uuid1", "uuid2"],
            "partial_sources": {"key1": ["item1", "item2"], "key2": ["item3"]},
        },
    ],
)
def test_api2_sources_validation_valid_requests(
    journalist_app, journalist_api_token, valid_request
):
    """Test that valid requests pass validation."""
    with journalist_app.test_client() as app:
        response = app.post(
            url_for("api2.sources"),
            json=valid_request,
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 200
