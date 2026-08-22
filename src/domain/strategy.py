"""The common interface every recovery strategy implements (B0, B1, and the
agent's orchestrator) so eval/harness.py can run them identically."""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain.actions import Action
from domain.context import Context
from domain.events import PaymentEvent


class Strategy(ABC):
    name: str

    @abstractmethod
    def propose(self, event: PaymentEvent, ctx: Context) -> Action | None:
        """Return the next proposed Action for this order given the current
        observable context, or None to stop (equivalent to ActionType.STOP).
        Must be a pure function of (event, ctx) — no strategy may hold
        cross-call state, so the harness (and audit replay) can call this
        deterministically at any point in a sequence."""
        raise NotImplementedError
