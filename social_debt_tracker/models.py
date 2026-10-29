"""Value types shared across the tracker.

Chat records carry identifier, title, and last-activity time. They have no
field for message text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class DebtStatus(str, Enum):
    ON_TRACK = "on_track"
    DUE = "due"
    OVERDUE = "overdue"
    SNOOZED = "snoozed"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class ChatMetadata:
    chat_id: int
    name: str
    last_message_at: datetime | None
    is_group: bool


@dataclass(frozen=True, slots=True)
class Circle:
    name: str
    target_days: int
    contacts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UserSettings:
    daily_report_hour: str
    privacy_mode: bool
    timezone: str
    report_interval_days: int


@dataclass(frozen=True, slots=True)
class AppConfig:
    user_settings: UserSettings
    circles: tuple[Circle, ...]


@dataclass(frozen=True, slots=True)
class DebtItem:
    contact_name: str
    circle_name: str
    target_days: int
    chat_id: int | None
    matched_name: str | None
    last_contact_at: datetime | None
    days_since: float | None
    saudade_index: float | None
    status: DebtStatus
    suggestion: str | None
    note: str | None


@dataclass
class ContactOverride:
    """Local feedback. Snooze hides a nag; a manual timestamp covers contact made outside Telegram."""

    name: str
    snooze_until: datetime | None = None
    manual_last_contact: datetime | None = None


@dataclass
class AppState:
    report_chat_id: int | None = None
    last_report_sent_at: datetime | None = None
    contacts: dict[str, ContactOverride] | None = None

    def __post_init__(self) -> None:
        if self.contacts is None:
            self.contacts = {}

    @property
    def contact_map(self) -> dict[str, ContactOverride]:
        if self.contacts is None:
            self.contacts = {}
        return self.contacts
