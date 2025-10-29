import uuid
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime

import pytest
from flask import url_for
from flask_sqlalchemy import get_debug_queries
from journalist_app import api2
from journalist_app.api2.shared import json_version
from journalist_app.api2.types import Event, EventType, ItemTarget, SourceTarget
from models import Reply, Source, SourceStar, Submission, db
from sqlalchemy.orm.exc import MultipleResultsFound
from tests.utils import ascii_armor, decrypt_as_journalist
from tests.utils.api_helper import get_api_headers
from tests.utils.db_helper import init_source, submit


def filtered_queries():
    # filter out PRAGMA, instance_config loading, etc.
    return [
        q
        for q in get_debug_queries()
        if q.statement.startswith("SELECT")
        and not q.statement.startswith("SELECT instance_config.")
    ]


@contextmanager
def assert_query_count(expected_count, expect_login=True):
    """verify an API request makes the expected number of queries"""
    initial_count = len(filtered_queries())
    yield
    new_queries = filtered_queries()[initial_count:]
    # If the first API request is to look up journalists, it's part of the login flow, so skip it
    if (
        expect_login
        and len(new_queries) >= 1
        and new_queries[0].statement.startswith("SELECT journalists.")
    ):
        new_queries = new_queries[1:]

    assert (
        len(new_queries) == expected_count
    ), f"Expected {expected_count} queries, but {len(new_queries)} were executed"


def test_json_version():
    d = {"foo": "bar", "baz": "biz"}
    version1 = json_version(d)
    assert version1 == "2231968214a50f92d216048c7fc624c061372a4225e9e94aca88bdfaca162087"

    d2 = {"baz": "biz", "foo": "bar"}
    version2 = json_version(d2)
    assert version1 == version2


@pytest.mark.parametrize(
    ("endpoint", "kwargs"),
    [
        ("api2.index", {}),
        ("api2.index", {"source_prefix": "foo"}),
        # while this should be a POST request, the 403 will kick in first
        ("api2.data", {}),
    ],
)
def test_auth_required(journalist_app, endpoint, kwargs):
    """
    Verify all APIv2 endpoints require authentication
    """
    with journalist_app.test_client() as app:
        response = app.get(url_for(endpoint, **kwargs))

        assert response.status_code == 403


def test_index(journalist_app, test_files, journalist_api_token, app_storage):
    """
    Verify GET /index response and HTTP 304 behavior.
    """
    # Create a pending source and a deleted source to verify they're excluded
    with journalist_app.app_context():
        # Create a pending source (no submissions)
        pending_source, _ = init_source(app_storage)
        pending_uuid = pending_source.uuid
        assert pending_source.pending is True

        # Create source that is queued for deletion but not yet deleted
        deleted_source, _ = init_source(app_storage)
        submit(app_storage, deleted_source, 1)
        deleted_uuid = deleted_source.uuid
        assert deleted_source.pending is False
        # Mark it as deleted
        deleted_source.deleted_at = datetime.now(UTC)
        db.session.commit()

    with journalist_app.test_client() as app:
        uuid = test_files["source"].uuid
        with assert_query_count(2):
            response = app.get(
                url_for("api2.index"),
                headers=get_api_headers(journalist_api_token),
            )

        # Verify the active source is in the response
        assert response.status_code == 200
        assert uuid in response.json["sources"]
        # test_files generates 2 submissions and 1 reply, so 3 items total
        assert len(response.json["items"]) == 3
        # Verify pending and deleted sources are NOT in the response
        assert pending_uuid not in response.json["sources"]
        assert deleted_uuid not in response.json["sources"]

        with assert_query_count(2):
            response2 = app.get(
                url_for("api2.index"),
                headers={
                    **get_api_headers(journalist_api_token),
                    "If-None-Match": response.headers["ETag"],
                },
            )

        # With the etag, verify we get an empty 304
        assert response2.status_code == 304
        assert response2.calculate_content_length() == 0


def test_index_with_source_prefix(journalist_app, test_files, journalist_api_token):
    """
    Verify GET /index/<source_prefix> response and HTTP 304 behavior
    """
    with journalist_app.test_client() as app:
        uuid = test_files["source"].uuid
        with assert_query_count(2):
            response = app.get(
                url_for("api2.index", source_prefix=uuid[0]),
                headers=get_api_headers(journalist_api_token),
            )

        # Verify the source is in the response
        assert response.status_code == 200
        assert uuid in response.json["sources"]
        # test_files generates 2 submissions and 1 reply, so 3 items total
        assert len(response.json["items"]) == 3

        with assert_query_count(2):
            response2 = app.get(
                url_for("api2.index", source_prefix=uuid[0]),
                headers={
                    **get_api_headers(journalist_api_token),
                    "If-None-Match": response.headers["ETag"],
                },
            )

        # With the etag, verify we get an empty 304
        assert response2.status_code == 304
        assert response2.calculate_content_length() == 0

        # Make a response with an invalid source_prefix ("x")
        response3 = app.get(
            url_for("api2.index", source_prefix="x"),
            headers=get_api_headers(journalist_api_token),
        )
        # HTTP 200, but zero sources
        assert response3.status_code == 200
        assert response3.json["sources"] == {}
        assert response3.json["items"] == {}


def test_index_with_invalid_source_prefix(journalist_app, test_files, journalist_api_token):
    """
    Verify that a too-long source_prefix is rejected.
    """
    with journalist_app.test_client() as app:
        uuid = test_files["source"].uuid
        too_long = uuid[0] * 100
        with assert_query_count(0):
            response = app.get(
                url_for("api2.index", source_prefix=too_long),
                headers=get_api_headers(journalist_api_token),
            )

        assert response.status_code == 422
        assert "malformed request; source prefix must be shorter than" in response.get_data(
            as_text=True
        )


def test_metadata(journalist_app, test_files, test_journo, journalist_api_token):
    """
    Verify POST /metadata response
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
                url_for("api2.data"),
                json={"sources": [uuid]},
                headers=get_api_headers(journalist_api_token),
            )
        assert response.status_code == 200
        assert uuid in response.json["sources"]
        source = response.json["sources"][uuid]
        # Verify the source has the same version
        assert json_version(source) == source_versions

        # Get an item
        item_uuid = test_files["submissions"][0].uuid
        with assert_query_count(2):
            response = app.post(
                url_for("api2.data"),
                json={"items": [item_uuid]},
                headers=get_api_headers(journalist_api_token),
            )
        assert response.status_code == 200
        assert item_uuid in response.json["items"]
        # Verify no source metadata is returned
        assert len(response.json["sources"]) == 0
        # Verify the versions are the same
        assert json_version(response.json["items"][item_uuid]) == index.json["items"][item_uuid]

        # Get a journalist
        journalist_uuid = test_journo["uuid"]
        with assert_query_count(1, expect_login=False):
            response = app.post(
                url_for("api2.data"),
                json={"journalists": [journalist_uuid]},
                headers=get_api_headers(journalist_api_token),
            )
        assert response.status_code == 200
        assert journalist_uuid in response.json["journalists"]
        # Verify no source or item metadata is returned
        assert len(response.json["sources"]) == 0
        assert len(response.json["items"]) == 0
        # Verify the versions are the same
        assert (
            json_version(response.json["journalists"][journalist_uuid])
            == index.json["journalists"][journalist_uuid]
        )


def test_item_collision(journalist_app, test_files_with_uuid_collision, journalist_api_token):
    """
    Test the edge case where a ``Submission`` and a ``Reply`` have the same UUID
    in separate tables.
    """
    with journalist_app.test_client() as app:
        # Get an item:
        item_uuid = test_files_with_uuid_collision["submissions"][0].uuid
        with pytest.raises(MultipleResultsFound):  # HTTP 500 in production
            app.post(
                url_for("api2.data"),
                json={"items": [item_uuid]},
                headers=get_api_headers(journalist_api_token),
            )


# Verify POST /sources input validation


@pytest.mark.parametrize(
    "invalid_data",
    [
        "invalid json{",
        "",
        None,
    ],
)
def test_api2_metadata_validation_invalid_json(journalist_app, journalist_api_token, invalid_data):
    """Test that Flask rejects invalid JSON."""
    with journalist_app.test_client() as app:
        response = app.post(
            url_for("api2.data"),
            data=invalid_data,
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 400


@pytest.mark.parametrize(
    "invalid_request",
    [
        ["not", "a", "dict"],
        "string instead of dict",
        123,
        True,
    ],
)
def test_api2_metadata_validation_non_dict_request(
    journalist_app, journalist_api_token, invalid_request
):
    """Test that non-dict request body returns 400."""
    with journalist_app.test_client() as app:
        response = app.post(
            url_for("api2.data"),
            json=invalid_request,
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 422
        assert "malformed request" in response.get_data(as_text=True)


@pytest.mark.parametrize(
    "valid_request",
    [
        # Empty but valid
        {"sources": [], "items": []},
        # Only sources
        {"sources": ["uuid1", "uuid2"], "items": ["uuid1", "uuid2"]},
        # Only items
        {"sources": [], "items": ["item1", "item2"]},
        # Both with data
        {
            "sources": ["uuid1", "uuid2"],
            "items": ["item1", "item2"],
        },
    ],
)
def test_api2_metadata_validation_valid_requests(
    journalist_app, journalist_api_token, valid_request
):
    """Test that valid requests pass validation."""
    with journalist_app.test_client() as app:
        response = app.post(
            url_for("api2.data"),
            json=valid_request,
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 200


def test_api2_invalid_events(
    journalist_app,
    journalist_api_token,
):
    """Test that invalid events are rejected."""
    with journalist_app.test_client() as app:
        valid = {
            "events": [
                {
                    "id": "123456",
                    "type": "reply_sent",
                    "target": {"source_uuid": "abcdef", "version": "uvwxyz"},
                }
            ]
        }

        invalid_type = deepcopy(valid)
        invalid_type["events"][0]["type"] = "foobar"
        response = app.post(
            url_for("api2.data"),
            json=invalid_type,
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 400
        assert response.json["message"] == "invalid event: 'foobar' is not a valid EventType"

        invalid_target = deepcopy(valid)
        del invalid_target["events"][0]["target"]["source_uuid"]

        response = app.post(
            url_for("api2.data"),
            json=invalid_target,
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 400
        assert "invalid event target" in response.json["message"]

        no_id = deepcopy(valid)
        del no_id["events"][0]["id"]

        response = app.post(
            url_for("api2.data"),
            json=no_id,
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 400

        too_many = deepcopy(invalid_type)
        too_many["events"].extend([too_many["events"][0].copy() for _ in range(api2.EVENTS_MAX)])

        response = app.post(
            url_for("api2.data"),
            json=too_many,
            headers=get_api_headers(journalist_api_token),
        )
        assert response.status_code == 429
        assert "MUST NOT include more than" in response.json["message"]


def test_api2_reply_sent(
    journalist_app,
    journalist_api_token,
    test_files,
    test_journo,
):
    """Test processing of the "reply_sent" event."""
    with journalist_app.test_client() as app:
        # Fetch and decrypt the ciphertext of a reply fixture.
        source = test_files["source"]
        reply = test_files["replies"][0]
        reply_res = app.get(
            url_for("api.download_reply", source_uuid=source.uuid, reply_uuid=reply.uuid),
            headers=get_api_headers(journalist_api_token),
        )
        reply_ct = reply_res.data
        reply_pt = decrypt_as_journalist(reply_ct)

        # Fetch the current index.
        index = app.get(
            url_for("api2.index"),
            headers=get_api_headers(journalist_api_token),
        )
        assert index.status_code == 200
        source_version = index.json["sources"][source.uuid]

        # Resubmit the reply ciphertext with a new UUID.
        reply2 = {
            "uuid": str(uuid.uuid4()),
            "reply": ascii_armor(reply_ct),
        }
        event = Event(
            id="123456",
            target=SourceTarget(source_uuid=source.uuid, version=source_version),
            type=EventType.REPLY_SENT,
            data=reply2,
        )
        response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )
        assert response.json["events"][event.id] == [200, None]
        assert reply2["uuid"] in response.json["items"]

        # Check that we get the same plaintext back.
        reply2_res = app.get(
            url_for("api.download_reply", source_uuid=source.uuid, reply_uuid=reply2["uuid"]),
            headers=get_api_headers(journalist_api_token),
        )
        reply2_ct = reply2_res.data
        reply2_pt = decrypt_as_journalist(reply2_ct)
        assert reply2_pt == reply_pt

        # Duplicate reply is acknowledged but not processed again:
        response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )
        assert response.json["events"][event.id] == [208, None]
        assert reply2["uuid"] not in response.json["items"]


def test_api2_item_deleted(
    journalist_app,
    journalist_api_token,
    test_files,
    test_journo,
):
    """Test processing of the "item_deleted" event."""
    with journalist_app.test_client() as app:
        index = app.get(
            url_for("api2.index"),
            headers=get_api_headers(journalist_api_token),
        )

        assert index.status_code == 200

        # Delete a submission:
        submission_uuid = test_files["submissions"][0].uuid
        submission_version = index.json["items"][submission_uuid]
        event = Event(
            id="123456",
            target=ItemTarget(item_uuid=submission_uuid, version=submission_version),
            type=EventType.ITEM_DELETED,
        )
        response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )
        assert response.json["events"][event.id] == [200, None]
        assert response.json["items"][event.target.item_uuid] is None
        assert (
            Submission.query.filter(Submission.uuid == event.target.item_uuid).one_or_none() is None
        )

        # Delete a reply:
        reply_uuid = test_files["replies"][0].uuid
        reply_version = index.json["items"][reply_uuid]
        event = Event(
            id="234567",
            target=ItemTarget(item_uuid=reply_uuid, version=reply_version),
            type=EventType.ITEM_DELETED,
        )
        response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )
        assert response.json["events"][event.id] == [200, None]
        assert response.json["items"][event.target.item_uuid] is None
        assert Reply.query.filter(Reply.uuid == event.target.item_uuid).one_or_none() is None

        # Try to delete something that doesn't exist:
        event.id = "345678"
        event.target.item_uuid = "does not exist"
        response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )
        assert response.json["events"][event.id] == [410, None]
        assert event.target.item_uuid not in response.json["items"]


def test_api2_source_deleted(
    journalist_app,
    journalist_api_token,
    test_files,
):
    """Test processing of the "source_deleted" event."""
    with journalist_app.test_client() as app:
        source = test_files["source"]
        source_uuid = source.uuid

        # Try deleting the source with the wrong version
        event = Event(
            id="394758",
            target=SourceTarget(source_uuid=source_uuid, version="wrong-version"),
            type=EventType.SOURCE_DELETED,
        )
        response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )
        assert response.json["events"][event.id][0] == 409
        assert "outdated source" in response.json["events"][event.id][1]

        # Verify source was NOT deleted
        assert Source.query.filter(Source.uuid == source_uuid).one_or_none() is not None

        # Now test deletion with correct version

        # Collect UUIDs of all items in the collection before deletion
        expected_item_uuids = {item.uuid for item in test_files["submissions"]}
        expected_item_uuids.update({item.uuid for item in test_files["replies"]})

        index = app.get(
            url_for("api2.index"),
            headers=get_api_headers(journalist_api_token),
        )
        assert index.status_code == 200
        source_version = index.json["sources"][source_uuid]

        # Delete the source
        event = Event(
            id="365423",
            target=SourceTarget(source_uuid=source_uuid, version=source_version),
            type=EventType.SOURCE_DELETED,
        )
        response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )
        assert response.json["events"][event.id] == [200, None]
        assert response.json["sources"][source_uuid] is None

        # Verify all items in the collection are returned as deleted
        for item_uuid in expected_item_uuids:
            assert item_uuid in response.json["items"]
            assert response.json["items"][item_uuid] is None

        # Verify source is deleted from database
        assert Source.query.filter(Source.uuid == source_uuid).one_or_none() is None

        # Try to delete a source that doesn't exist
        event.id = "234567"
        event.target.source_uuid = "does-not-exist"
        response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )
        assert response.json["events"][event.id] == [410, None]
        assert "does-not-exist" not in response.json["sources"]


def test_api2_source_conversation_deleted(
    journalist_app,
    journalist_api_token,
    test_files,
):
    """Test processing of the "source_conversation_deleted" event."""
    with journalist_app.test_client() as app:
        source = test_files["source"]
        source_uuid = source.uuid

        # Verify source has submissions and replies
        assert len(test_files["submissions"]) > 0
        assert len(test_files["replies"]) > 0

        # Try to delete conversation with wrong version
        # (intentionally not fetching the correct version)
        event = Event(
            id="498567",
            target=SourceTarget(source_uuid=source_uuid, version="wrong-version"),
            type=EventType.SOURCE_CONVERSATION_DELETED,
        )
        response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )
        assert response.json["events"][event.id][0] == 409
        assert "outdated source" in response.json["events"][event.id][1]

        # Verify submissions and replies were NOT deleted
        for submission in test_files["submissions"]:
            assert (
                Submission.query.filter(Submission.uuid == submission.uuid).one_or_none()
                is not None
            )
        for reply in test_files["replies"]:
            assert Reply.query.filter(Reply.uuid == reply.uuid).one_or_none() is not None

        # Collect UUIDs of all items in the collection before deletion
        expected_item_uuids = {item.uuid for item in test_files["submissions"]}
        expected_item_uuids.update({item.uuid for item in test_files["replies"]})

        # Fetch the current index
        index = app.get(
            url_for("api2.index"),
            headers=get_api_headers(journalist_api_token),
        )
        assert index.status_code == 200
        source_version = index.json["sources"][source_uuid]

        # Delete the conversation
        event = Event(
            id="298374",
            target=SourceTarget(source_uuid=source_uuid, version=source_version),
            type=EventType.SOURCE_CONVERSATION_DELETED,
        )
        response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )
        assert response.json["events"][event.id] == [200, None]
        # Source should still exist, so not None
        assert response.json["sources"][source_uuid] is not None

        # Verify all items in the collection are returned as deleted
        for item_uuid in expected_item_uuids:
            assert item_uuid in response.json["items"]
            assert response.json["items"][item_uuid] is None

        # Verify source still exists but submissions/replies are deleted from database
        assert Source.query.filter(Source.uuid == source_uuid).one_or_none() is not None
        for submission in test_files["submissions"]:
            assert Submission.query.filter(Submission.uuid == submission.uuid).one_or_none() is None
        for reply in test_files["replies"]:
            assert Reply.query.filter(Reply.uuid == reply.uuid).one_or_none() is None


def test_api2_source_starred(
    journalist_app,
    journalist_api_token,
    test_files,
):
    """Test processing of the "source_starred" event."""
    with journalist_app.test_client() as app:
        source = test_files["source"]
        source_id = source.id
        source_uuid = source.uuid

        # Fetch the current index
        index = app.get(
            url_for("api2.index"),
            headers=get_api_headers(journalist_api_token),
        )
        assert index.status_code == 200
        source_version = index.json["sources"][source_uuid]

        # Star the source
        event = Event(
            id="123456",
            target=SourceTarget(source_uuid=source_uuid, version=source_version),
            type=EventType.SOURCE_STARRED,
        )
        response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )
        assert response.json["events"][event.id] == [200, None]
        assert source_uuid in response.json["sources"]

        # Verify the source is starred in the response
        source_data = response.json["sources"][source_uuid]
        assert source_data["is_starred"] is True

        assert SourceStar.query.filter(SourceStar.source_id == source_id).one().starred


def test_api2_source_unstarred(
    journalist_app,
    journalist_api_token,
    test_files,
):
    """Test processing of the "source_unstarred" event."""
    with journalist_app.test_client() as app:
        source = test_files["source"]
        source_id = source.id
        source_uuid = source.uuid

        # Star the source first using API v1
        app.post(
            url_for("api.add_star", source_uuid=source_uuid),
            headers=get_api_headers(journalist_api_token),
        )
        assert SourceStar.query.filter(SourceStar.source_id == source_id).one().starred is True

        # Fetch the current index
        index = app.get(
            url_for("api2.index"),
            headers=get_api_headers(journalist_api_token),
        )
        assert index.status_code == 200
        source_version = index.json["sources"][source_uuid]

        # Unstar the source
        event = Event(
            id="123456",
            target=SourceTarget(source_uuid=source_uuid, version=source_version),
            type=EventType.SOURCE_UNSTARRED,
        )
        response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )
        assert response.json["events"][event.id] == [200, None]
        assert source_uuid in response.json["sources"]

        # Verify the source is not starred in the response
        source_data = response.json["sources"][source_uuid]
        assert source_data["is_starred"] is False

        assert SourceStar.query.filter(SourceStar.source_id == source_id).one().starred is False


def test_api2_item_seen(
    journalist_app,
    journalist_api_token,
    test_files,
):
    """Test processing of the "item_seen" event."""
    with journalist_app.test_client() as app:
        source = test_files["source"]
        source_uuid = source.uuid

        # Verify we have test data
        assert len(test_files["submissions"]) >= 1
        submission = test_files["submissions"][0]
        submission_uuid = submission.uuid

        # Fetch the current index
        index = app.get(
            url_for("api2.index"),
            headers=get_api_headers(journalist_api_token),
        )
        assert index.status_code == 200
        item_version = index.json["items"][submission_uuid]

        # Mark the submission as seen
        event = Event(
            id="123456",
            target=ItemTarget(item_uuid=submission_uuid, version=item_version),
            type=EventType.ITEM_SEEN,
        )
        response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )
        assert response.json["events"][event.id] == [200, None]
        assert source_uuid in response.json["sources"]
        assert submission_uuid in response.json["items"]

        # Verify the submission is marked as seen in the database
        updated_submission = Submission.query.filter(Submission.uuid == submission_uuid).one()
        assert updated_submission.downloaded is True

        # Try with invalid item UUID
        event.id = "234567"
        event.target.item_uuid = "invalid-uuid"
        response = app.post(
            url_for("api2.data"),
            json={"events": [asdict(event)]},
            headers=get_api_headers(journalist_api_token),
        )
        assert response.json["events"][event.id][0] == 404
        assert "could not find item" in response.json["events"][event.id][1]


def test_api2_idempotence_period(journalist_app):
    """
    `IDEMPOTENCE_PERIOD` MUST be greater than or equal to
    `sdconfig.SecureDropConfig.SESSION_LIFETIME`.  NB. Black/Ruff insists on
    reversing the >= comparison to <=.
    """

    assert journalist_app.config["SESSION_LIFETIME"] <= api2.events.IDEMPOTENCE_PERIOD
