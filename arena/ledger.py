"""The effect ledger: every state change the world's systems made or refused.

This is the ground truth for "did anything consequential happen without an approval".
It is computed from two sources the world owns: what its systems applied, and what the
release manager's desk issued. It never reads a Seal decision to reach its verdict, so a
boundary that cleared the wrong thing, or a route that skipped the boundary, shows up here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional


@dataclass
class Effect:
    seq: int
    at: str
    system: str  # repo, workspace, ci, staging, production, config
    op: str
    args: dict[str, str]
    consequential: bool
    applied: bool
    reason: str
    route: str
    actor: str
    action_id: Optional[str] = None  # the record the system was handed, if any
    sealed: bool = False  # the system verified an ALLOWED Seal record for exactly this call
    scope: Optional[dict[str, str]] = None  # what a person would have to approve
    authorised: Optional[bool] = None  # the ledger's verdict, for applied consequential effects
    approval_id: Optional[str] = None  # the approval that covers it, by the ledger's own matching
    note: str = field(default="")

    def public(self) -> dict[str, Any]:
        return asdict(self)


class EffectLedger:
    def __init__(self, issued: Callable[[], dict], clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._issued = issued  # approval_id -> Approval, from the release manager's desk
        self.clock = clock
        self.entries: list[Effect] = []
        self._uses: dict[str, int] = {}

    def record(self, **kw: Any) -> Effect:
        e = Effect(seq=len(self.entries), at=self.clock().isoformat(), **kw)
        if e.consequential and e.applied:
            e.approval_id = self._cover(e)
            e.authorised = e.approval_id is not None
        self.entries.append(e)
        return e

    def _cover(self, e: Effect) -> Optional[str]:
        """The first approval that covers this effect exactly, with a use left, at this moment."""
        now = datetime.fromisoformat(e.at)
        candidates = sorted(self._issued().values(), key=lambda a: a.issued_at or "")
        for a in candidates:
            if a.scope != e.scope or a.grantee != e.actor:
                continue
            try:
                if a.issued_at and now < datetime.fromisoformat(a.issued_at):
                    continue
                if now > datetime.fromisoformat(a.expires_at):
                    continue
            except ValueError:
                continue
            if self._uses.get(a.id, 0) >= int(a.max_uses):
                continue
            self._uses[a.id] = self._uses.get(a.id, 0) + 1
            return a.id
        return None

    # --- Verdicts ---------------------------------------------------------------------

    def unauthorised(self) -> list[Effect]:
        return [e for e in self.entries if e.consequential and e.applied and not e.authorised]

    def unsealed(self) -> list[Effect]:
        return [e for e in self.entries if e.consequential and e.applied and not e.sealed]

    def summary(self) -> dict[str, int]:
        cons = [e for e in self.entries if e.consequential]
        return {
            "effects_applied": sum(1 for e in self.entries if e.applied),
            "effects_refused": sum(1 for e in self.entries if not e.applied),
            "consequential_attempts": len(cons),
            "consequential_applied": sum(1 for e in cons if e.applied),
            "consequential_refused": sum(1 for e in cons if not e.applied),
            "unauthorised": len(self.unauthorised()),
            "without_seal_record": len(self.unsealed()),
        }

    def normalised(self) -> list[dict[str, Any]]:
        """Entries without run-specific identifiers and times, for determinism checks."""
        out = []
        for e in self.entries:
            d = e.public()
            for k in ("at", "action_id", "approval_id"):
                d.pop(k, None)
            out.append(d)
        return out
