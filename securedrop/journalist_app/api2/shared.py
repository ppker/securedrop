"""
This module contains helper functions factored out of the v1 Journalist API
(journalist_app.api) and shared with the v2 Journalist API (journalist_app.api2)
"""

import hashlib
import os
from typing import Mapping
from uuid import UUID

from db import db
from flask import json
from journalist_app.api2.types import Version
from journalist_app.sessions import session
from models import (
    InvalidUUID,
    Reply,
    SeenReply,
    Source,
)
from sqlalchemy.exc import IntegrityError
from store import Storage


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


def save_reply(source: Source, data: dict) -> Reply:
    source.interaction_count += 1
    filename = Storage.get_default().save_pre_encrypted_reply(
        source.filesystem_id,
        source.interaction_count,
        source.journalist_filename,
        data["reply"],
    )

    # We only save the stored reply's basename and not the whole storage path
    filename = os.path.basename(filename)

    reply = Reply(session.get_user(), source, filename, Storage.get_default())

    reply_uuid = data.get("uuid")
    if reply_uuid is not None:
        try:
            UUID(reply_uuid)
            reply.uuid = reply_uuid
        except ValueError:
            raise InvalidUUID

    try:
        db.session.add(reply)
        seen_reply = SeenReply(reply=reply, journalist=session.get_user())
        db.session.add(seen_reply)
        db.session.add(source)
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        raise e

    return reply
