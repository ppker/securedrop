from db import db
from journalist_app import utils
from journalist_app.api2.shared import save_reply
from journalist_app.api2.types import (
    Event,
    EventResult,
    EventStatusCode,
    EventType,
    ItemTarget,
    SourceTarget,
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
            event.type = EventType(event.type)  # strict enum
            if "source_uuid" in event.target:
                event.target = SourceTarget(**event.target)
            elif "item_uuid" in event.target:
                event.target = ItemTarget(**event.target)
            else:
                raise TypeError("invalid event target")

        except (TypeError, ValueError) as e:
            return EventResult(
                event_id=event.id,
                status=(EventStatusCode.BadRequest, str(e)),
            )

        if self.has_processed(event):
            return EventResult(
                event_id=event.id,
                status=(EventStatusCode.AlreadyReported, None),
            )

        try:
            handler = {
                "item_deleted": self.handle_item_deleted,
                "reply_sent": self.handle_reply_sent,
            }[event.type]
        except KeyError:
            return EventResult(
                event_id=event.id,
                status=(EventStatusCode.NotImplemented, f"no handler for event type: {event.type}"),
            )

        result = handler(event)
        self.mark_as_processed(event, result)
        return result

    def idempotence_key(self, event: Event) -> str:
        return f"{REDIS_EVENT_PREFIX}/{self._session.user.uuid}/{event.id}"

    def has_processed(self, event: Event) -> bool:
        return self._redis.get(self.idempotence_key(event)) is not None

    def mark_as_processed(self, event: Event, result: EventResult) -> None:
        self._redis.set(
            self.idempotence_key(event),
            result.status[0],
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

        reply = save_reply(source, event.data)
        db.session.refresh(source)

        return EventResult(
            event_id=event.id,
            status=(EventStatusCode.OK, None),
            sources={source.uuid: source},
            items={reply.uuid: reply},
        )
