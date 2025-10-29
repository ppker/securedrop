from dataclasses import dataclass, field
from enum import IntEnum, StrEnum, auto
from typing import (
    Any,
    List,
    Mapping,
    NewType,
    Optional,
    Set,
    Tuple,
)

Record = NewType("Record", dict[str, Any])
Version = NewType("Version", str)


# NB.  Ideally we'd have a generic UUID[T], but the semantics don't change
# before mypy 1.12, which is incompatible with our use elsewhere of sqlmypy.
ReplyUUID = NewType("ReplyUUID", str)
SourceUUID = NewType("SourceUUID", str)
ItemUUID = NewType("ItemUUID", str)
JournalistUUID = NewType("JournalistUUID", str)


EventID = NewType("EventID", str)  # int, but opaque on the wire


class EventType(StrEnum):
    REPLY_SENT = auto()
    ITEM_DELETED = auto()
    ITEM_SEEN = auto()
    SOURCE_DELETED = auto()
    SOURCE_CONVERSATION_DELETED = auto()
    SOURCE_STARRED = auto()
    SOURCE_UNSTARRED = auto()


class EventStatusCode(IntEnum):
    Processing = 102
    OK = 200
    # We already saw and processed this event
    AlreadyReported = 208
    BadRequest = 400
    # The target UUID doesn't exist (non-deletion requests)
    NotFound = 404
    # Provided version is out of date and it was a deletion request
    Conflict = 409
    # The target UUID doesn't exist and it was a deletion request
    Gone = 410
    NotImplemented = 501


EventStatus = Tuple[EventStatusCode, Optional[str]]


@dataclass
class Index:
    # Source metadata, optionally filtered by `source_prefix`:
    sources: dict[SourceUUID, Version] = field(default_factory=dict)
    items: dict[ItemUUID, Version] = field(default_factory=dict)

    # Non-source metadata (always returned):
    journalists: dict[JournalistUUID, Version] = field(default_factory=dict)


@dataclass
class Target:
    """Base class for `<Resource>Target` dataclasses, to make their union usable
    at runtime.  Subclass at least with:

        <resource>_uuid: <Resource>UUID

    """

    version: Version


@dataclass
class SourceTarget(Target):
    source_uuid: SourceUUID


@dataclass
class ItemTarget(Target):
    item_uuid: ItemUUID


@dataclass
class EventData:
    """
    Base class for `<EventType>Data dataclasses, to make their union usable at runtime.
    For non-empty events, subclass and add to `EVENT_DATA_TYPES`.
    """


@dataclass
class ReplySentData(EventData):
    uuid: ReplyUUID
    reply: str


EVENT_DATA_TYPES = {EventType.REPLY_SENT: ReplySentData}


@dataclass
class Event:
    id: EventID
    target: Target | Mapping
    type: EventType
    data: Optional[EventData | Mapping] = None

    def __post_init__(self) -> None:
        if not isinstance(self.type, EventType):
            self.type = EventType(self.type)  # strict enum

        if not isinstance(self.target, Target):
            if "source_uuid" in self.target:
                self.target = SourceTarget(**self.target)
            elif "item_uuid" in self.target:
                self.target = ItemTarget(**self.target)
            else:
                raise TypeError(f"invalid event target: {self.target}")

        if not isinstance(self.data, EventData) and self.data and self.type in EVENT_DATA_TYPES:
            try:
                self.data = EVENT_DATA_TYPES[self.type](**self.data)
            except TypeError:
                raise TypeError(f"invalid event data for type {self.type}")
        else:
            self.data = None


@dataclass
class EventResult:
    event_id: EventID
    status: EventStatus

    # Changed sources/items, return {<uuid>: None} to indicate deletion:
    sources: dict[SourceUUID, Optional[Record]] = field(default_factory=dict)
    items: dict[ItemUUID, Optional[Record]] = field(default_factory=dict)


@dataclass
class BatchRequest:
    # Source metadata:
    sources: Set[SourceUUID] = field(default_factory=set)
    items: Set[ItemUUID] = field(default_factory=set)

    # Non-source metadata:
    journalists: Set[JournalistUUID] = field(default_factory=set)

    # Events submitted by the client:
    events: List[Event] = field(default_factory=list)


@dataclass
class BatchResponse:
    """
    In dictionaries keyed by UUID, an entry {<uuid>: None} indicates deletion.
    """

    # Source metadata:
    sources: dict[SourceUUID, Optional[Record]] = field(default_factory=dict)
    items: dict[ItemUUID, Optional[Record]] = field(default_factory=dict)

    # Non-source metadata:
    journalists: dict[JournalistUUID, Optional[Record]] = field(default_factory=dict)

    # Events processed by the server:
    events: dict[EventID, EventStatus] = field(default_factory=dict)
