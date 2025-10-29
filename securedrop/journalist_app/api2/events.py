from db import db
from journalist_app import utils
from journalist_app.api2.shared import json_version, save_reply
from journalist_app.api2.types import (
    Event,
    EventResult,
    EventStatusCode,
    EventType,
    ItemUUID,
)
from journalist_app.sessions import Session, session
from models import Reply, Source, Submission
from redis import Redis
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound

# `IDEMPOTENCE_PERIOD` MUST be greater than or equal to
# `sdconfig.SecureDropConfig.SESSION_LIFETIME`.  In practice, 24 hours is the
# easiest period to reason about.
IDEMPOTENCE_PERIOD = 60 * 60 * 24  # seconds * minutes * hours = 1 day

REDIS_EVENT_PREFIX = "sd/events"


class EventHandler:
    """
    This class is the per-request context for handling events.  To add a handler
    for a new event `thing_done`, you must:

    1. define the enum value `EventType.THING_DONE` in journalist_api2.types;

    2. define the handler as a static method `handle_thing_done(event: Event)`
       in this class

    3. explicitly register `{"thing_done": self.handle_thing_done}` inside
      `EventHandler.process()`.

    This is belt-and-suspenders for ensuring that only the intended methods are
    exposed as callable event handlers.
    """

    def __init__(self, session: Session, redis: Redis) -> None:
        self._session = session
        self._redis = redis

    def process(self, event: Event) -> EventResult:
        """The per-event entry-point for handling a single event."""

        try:
            if self.has_progress(event):
                return EventResult(
                    event_id=event.id,
                    status=(EventStatusCode.AlreadyReported, None),
                )

            handler = {
                EventType.ITEM_DELETED: self.handle_item_deleted,
                EventType.ITEM_SEEN: self.handle_item_seen,
                EventType.REPLY_SENT: self.handle_reply_sent,
                EventType.SOURCE_DELETED: self.handle_source_deleted,
                EventType.SOURCE_CONVERSATION_DELETED: self.handle_source_conversation_deleted,
                EventType.SOURCE_STARRED: self.handle_source_starred,
                EventType.SOURCE_UNSTARRED: self.handle_source_unstarred,
            }[event.type]
        except KeyError:
            return EventResult(
                event_id=event.id,
                status=(
                    EventStatusCode.NotImplemented,
                    f"no handler for event type: {event.type}",
                ),
            )

        self.mark_progress(event)  # prevent races
        result = handler(event)
        self.mark_progress(event, result.status[0])  # enforce idempotence
        return result

    def idempotence_key(self, event: Event) -> str:
        return f"{REDIS_EVENT_PREFIX}/{self._session.user.uuid}/{event.id}"

    def has_progress(self, event: Event) -> EventStatusCode:
        return self._redis.get(self.idempotence_key(event))

    def mark_progress(
        self, event: Event, status: EventStatusCode = EventStatusCode.Processing
    ) -> None:
        self._redis.set(
            self.idempotence_key(event),
            status,
            ex=IDEMPOTENCE_PERIOD,
        )

    @staticmethod
    def handle_item_deleted(event: Event) -> EventResult:
        item = find_item(event.target.item_uuid)
        if item is None:
            return EventResult(
                event_id=event.id,
                status=(EventStatusCode.Gone, None),
            )

        utils.delete_file_object(item)
        return EventResult(
            event_id=event.id,
            status=(EventStatusCode.OK, None),
            items={event.target.item_uuid: None},
        )

    @staticmethod
    def handle_reply_sent(event: Event) -> EventResult:
        try:
            source = Source.query.filter(Source.uuid == event.target.source_uuid).one()
        except NoResultFound:
            return EventResult(
                event_id=event.id,
                status=(
                    EventStatusCode.NotFound,
                    f"could not find source: {event.target.source_uuid}",
                ),
            )

        reply = save_reply(source, event.data)
        db.session.refresh(source)

        return EventResult(
            event_id=event.id,
            status=(EventStatusCode.OK, None),
            sources={source.uuid: source},
            items={reply.uuid: reply},
        )

    @staticmethod
    def handle_source_deleted(event: Event) -> EventResult:
        try:
            source = Source.query.filter(Source.uuid == event.target.source_uuid).one()
        except NoResultFound:
            return EventResult(
                event_id=event.id,
                status=(
                    EventStatusCode.Gone,
                    None,
                ),
            )

        current_version = json_version(source.to_api_v2())
        if event.target.version != current_version:
            return EventResult(
                event_id=event.id,
                status=(
                    EventStatusCode.Conflict,
                    f"outdated source: expected {current_version}, got {event.target.version}",
                ),
            )

        # Mark as deleted all the items in the source's collection
        deleted_items = {item.uuid: None for item in source.collection}

        utils.delete_collection(source.filesystem_id)
        return EventResult(
            event_id=event.id,
            status=(EventStatusCode.OK, None),
            sources={event.target.source_uuid: None},
            items=deleted_items,
        )

    @staticmethod
    def handle_source_conversation_deleted(event: Event) -> EventResult:
        try:
            source = Source.query.filter(Source.uuid == event.target.source_uuid).one()
        except NoResultFound:
            return EventResult(
                event_id=event.id,
                status=(
                    EventStatusCode.Gone,
                    None,
                ),
            )

        current_version = json_version(source.to_api_v2())
        if event.target.version != current_version:
            return EventResult(
                event_id=event.id,
                status=(
                    EventStatusCode.Conflict,
                    f"outdated source: expected {current_version}, got {event.target.version}",
                ),
            )

        # Mark as deleted all the items in the source's collection
        deleted_items = {item.uuid: None for item in source.collection}

        utils.delete_source_files(source.filesystem_id)
        db.session.refresh(source)

        return EventResult(
            event_id=event.id,
            status=(EventStatusCode.OK, None),
            sources={source.uuid: source},
            items=deleted_items,
        )

    @staticmethod
    def handle_source_starred(event: Event) -> EventResult:
        try:
            source = Source.query.filter(Source.uuid == event.target.source_uuid).one()
        except NoResultFound:
            return EventResult(
                event_id=event.id,
                status=(
                    EventStatusCode.NotFound,
                    f"could not find source: {event.target.source_uuid}",
                ),
            )

        utils.make_star_true(source.filesystem_id)
        db.session.commit()
        db.session.refresh(source)

        return EventResult(
            event_id=event.id,
            status=(EventStatusCode.OK, None),
            sources={source.uuid: source},
        )

    @staticmethod
    def handle_source_unstarred(event: Event) -> EventResult:
        try:
            source = Source.query.filter(Source.uuid == event.target.source_uuid).one()
        except NoResultFound:
            return EventResult(
                event_id=event.id,
                status=(
                    EventStatusCode.NotFound,
                    f"could not find source: {event.target.source_uuid}",
                ),
            )

        utils.make_star_false(source.filesystem_id)
        db.session.commit()
        db.session.refresh(source)

        return EventResult(
            event_id=event.id,
            status=(EventStatusCode.OK, None),
            sources={source.uuid: source},
        )

    @staticmethod
    def handle_item_seen(event: Event) -> EventResult:
        item = find_item(event.target.item_uuid)
        if item is None:
            return EventResult(
                event_id=event.id,
                status=(EventStatusCode.NotFound, f"could not find item: {event.target.item_uuid}"),
            )

        # Mark it as seen
        utils.mark_seen([item], session.get_user())

        # Refresh and return
        source = item.source
        db.session.refresh(source)
        db.session.refresh(item)

        return EventResult(
            event_id=event.id,
            status=(EventStatusCode.OK, None),
            sources={source.uuid: source},
            items={item.uuid: item},
        )


def find_item(item_uuid: ItemUUID) -> Submission | Reply | None:
    submission = Submission.query.filter(Submission.uuid == item_uuid).one_or_none()
    reply = Reply.query.filter(Reply.uuid == item_uuid).one_or_none()

    if submission and reply:
        # Fail if we get unlucky and hit a UUID collision between the
        # `Submission` and `Reply` tables.  This is vanishingly unlikely,
        # but SQLite can't enforce uniqueness between them.
        raise MultipleResultsFound(f"found {item_uuid} in both submissions and replies")

    return submission or reply
