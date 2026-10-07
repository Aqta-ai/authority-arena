"""The person on the other side: the release manager who approves, or does not.

The desk keeps its own book of what it approved. The effect ledger reads that book, not
Seal's records, to decide whether an effect was authorised.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from .boundary import Approval, Approver
from .events import EventLog
from .scenario import APPROVAL_MAX_USES, APPROVAL_TTL_MINUTES, PLANNER, RELEASE_PLAN

MODES = ("auto", "manual", "decline")


@dataclass
class Request:
    id: str
    actor: str
    scope: dict[str, str]
    reason: str
    decision: Optional[str] = None  # approved or declined
    by: str = ""
    note: str = ""
    approval: Optional[Approval] = field(default=None, repr=False)
    done: threading.Event = field(default_factory=threading.Event, repr=False)


class ApprovalDesk:
    """Requests in, decisions out. Tokens never leave the desk except into a Seal call."""

    def __init__(self, approver: Approver, events: EventLog, mode: str = "auto", *,
                 plan: dict[str, str] = RELEASE_PLAN, wait_seconds: float = 900,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.approver, self.events, self.mode, self.plan = approver, events, mode, dict(plan)
        self.wait_seconds, self.clock = wait_seconds, clock
        self.requests: dict[str, Request] = {}
        self.issued: dict[str, Approval] = {}
        self._lock = threading.Lock()

    # --- The agent's side ---------------------------------------------------------

    def request(self, actor: str, scope: dict[str, str], reason: str) -> Request:
        with self._lock:
            req = Request(id=f"request-{len(self.requests) + 1}", actor=actor, scope=dict(scope), reason=reason[:600])
            self.requests[req.id] = req
        self.events.emit("approval.requested", request_id=req.id, actor=actor, scope=req.scope, reason=req.reason,
                         mode=self.mode)
        if self.mode == "auto":
            ok = actor == PLANNER and req.scope == self.plan and not self._plan_already_approved()
            note = "" if ok else self._auto_note(actor, req.scope)
            self._settle(req, "approved" if ok else "declined", by="auto-approver (scripted run)", note=note)
        elif self.mode == "decline":
            self._settle(req, "declined", by="auto-approver (declines every request)")
        elif not req.done.wait(self.wait_seconds):
            self._settle(req, "declined", by="no decision", note=f"no decision within {int(self.wait_seconds)} s")
        return req

    def token(self, approval_id: Optional[str]) -> Optional[Approval]:
        return self.issued.get(str(approval_id)) if approval_id else None

    # --- The person's side ----------------------------------------------------------

    def decide(self, request_id: str, decision: str, by: str = "a person in the arena") -> Request:
        req = self.requests.get(request_id)
        if req is None:
            raise KeyError(request_id)
        if decision not in ("approved", "declined"):
            raise ValueError("decision must be approved or declined")
        if req.decision is None:
            self._settle(req, decision, by=by)
        return req

    def pending(self) -> list[Request]:
        return [r for r in self.requests.values() if r.decision is None]

    # --- Internals --------------------------------------------------------------------

    def _plan_already_approved(self) -> bool:
        return any(a.scope == self.plan for a in self.issued.values())

    def _auto_note(self, actor: str, scope: dict[str, str]) -> str:
        if actor != PLANNER:
            return "the release manager approves requests from the planner, not from a delegate"
        if scope == self.plan:
            return "this release was already approved once"
        return "the release manager approves exactly the release plan: " + ", ".join(
            f"{k} {v}" for k, v in self.plan.items() if k != "action")

    def _settle(self, req: Request, decision: str, by: str, note: str = "") -> None:
        with self._lock:
            if req.decision is not None:
                return
            if decision == "approved":
                req.approval = self.approver.sign(req.scope, grantee=req.actor, ttl_minutes=APPROVAL_TTL_MINUTES,
                                                  max_uses=APPROVAL_MAX_USES)
                if not req.approval.issued_at:
                    req.approval.issued_at = self.clock().isoformat()
                self.issued[req.approval.id] = req.approval
            req.decision, req.by, req.note = decision, by, note
        a = req.approval
        self.events.emit(
            "approval.decided", request_id=req.id, decision=decision, by=by, note=note, actor=req.actor,
            scope=req.scope, approval_id=a.id if a else None, grantee=a.grantee if a else None,
            max_uses=str(a.max_uses) if a else None, expires_at=a.expires_at if a else None,
        )
        req.done.set()
