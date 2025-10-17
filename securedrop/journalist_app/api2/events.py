from dataclasses import asdict

from db import db
from journalist_app import utils
from journalist_app.api2.shared import save_reply
from journalist_app.api2.types import (
    Event,
    EventResult,
    EventStatusCode,
    EventType,
)
from journalist_app.sessions import Session
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
                EventType.REPLY_SENT: self.handle_reply_sent,
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
        submission = Submission.query.filter(
            Submission.uuid == event.target.item_uuid
        ).one_or_none()
        reply = Reply.query.filter(Reply.uuid == event.target.item_uuid).one_or_none()

        if submission and reply:
            # Fail if we get unlucky and hit a UUID collision between the
            # `Submission` and `Reply` tables.  This is vanishingly unlikely,
            # but SQLite can't enforce uniqueness between them.
            raise MultipleResultsFound(
                f"found {event.target.item_uuid} in both submissions and replies"
            )

        item = submission or reply
        if item is None:
            return EventResult(
                event_id=event.id,
                status=(EventStatusCode.NotFound, f"could not find item: {event.target.item_uuid}"),
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

        reply = save_reply(source, asdict(event.data))
        db.session.refresh(source)

        return EventResult(
            event_id=event.id,
            status=(EventStatusCode.OK, None),
            sources={source.uuid: source},
            items={reply.uuid: reply},
        )
