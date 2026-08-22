"""Pure customer/account types. Zero I/O, zero imports from other src/ packages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Customer:
    customer_id: str
    name: str
    timezone: str = "Asia/Kolkata"
    do_not_contact: bool = False
    risk_flagged: bool = False
    last_contacted_at: datetime | None = None


@dataclass(frozen=True)
class ContactEvent:
    customer_id: str
    channel: str
    sent_at: datetime
    payment_id: str | None = None
