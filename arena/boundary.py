"""The authority boundary as the arena sees it: one call before every effect.

The arena talks to Seal over HTTP and nothing else: POST /v1/actions/authorize for each
decision, GET /v1/attestation/public-key once for the issuer key it pins. How an
organisation's rules are set up and how an approver's key signs an approval are the
deployment's business, so they arrive through an adapter (see `connect`). This keeps the
arena usable against any Seal deployment and keeps the gateway's internals out of it.
"""
from __future__ import annotations

import importlib.util
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol

import httpx

ALLOWED, NEEDS_APPROVAL, REFUSED = "allowed", "needs_approval", "refused"


@dataclass
class Approval:
    """A person's approval for exactly one scope. The token is opaque to the arena."""

    id: str
    scope: dict[str, str]
    grantee: str
    max_uses: int
    expires_at: str
    issued_at: str = ""
    token: Any = field(default=None, repr=False, compare=False)


@dataclass
class Decision:
    actor: str
    tool: str
    args: dict[str, str]
    outcome: str  # ALLOWED or BLOCKED, as signed
    kind: str  # allowed, needs_approval or refused
    reason: str  # public wording; empty when allowed
    action_id: str
    record: Optional[dict]
    bound_args: Optional[dict] = field(default=None, repr=False)
    approval_id: Optional[str] = None

    @property
    def allowed(self) -> bool:
        return self.outcome == "ALLOWED"


class Boundary(Protocol):
    label: str
    issuer_key: str
    org_id: str
    reference_keys: frozenset[str]

    def authorize(self, actor: str, tool: str, args: Mapping[str, str], approval: Optional[Approval] = None) -> Decision:
        ...


class Approver(Protocol):
    def sign(self, scope: Mapping[str, str], grantee: str, ttl_minutes: int, max_uses: int) -> Approval:
        ...


@dataclass
class Connection:
    boundary: Boundary
    approver: Approver
    facts: dict[str, str]  # public facts shown in the arena: gateway label, issuer key, key id


class Hooks(Protocol):
    """What a deployment adapter supplies to the HTTP client."""

    reference_keys: frozenset[str]

    def attach(self, args: Mapping[str, str], approval: Optional[Approval]) -> dict: ...

    def classify(self, response: Mapping[str, Any]) -> tuple[str, str]: ...

    def bound_args(self, response: Mapping[str, Any], args: Mapping[str, str]) -> Optional[dict]: ...


class SealHTTPBoundary:
    """POST /v1/actions/authorize, one call per effect, one API key per actor."""

    def __init__(self, base_url: str, *, keys: Mapping[str, str], agent_names: Mapping[str, str], org_id: str,
                 issuer_key: str, hooks: Hooks, label: str = "Seal"):
        self.base_url = base_url.rstrip("/")
        self._keys = dict(keys)
        self.agent_names = dict(agent_names)
        self.org_id = org_id
        self.issuer_key = issuer_key
        self.hooks = hooks
        self.label = label
        self.reference_keys = frozenset(hooks.reference_keys)
        self._http = httpx.Client(timeout=30)

    def __repr__(self) -> str:  # never print keys
        return f"SealHTTPBoundary({self.base_url!r}, actors={sorted(self._keys)})"

    def authorize(self, actor: str, tool: str, args: Mapping[str, str], approval: Optional[Approval] = None) -> Decision:
        if actor not in self._keys:
            raise KeyError(f"no Seal key for actor {actor!r}")
        body = {"tool": tool, "args": self.hooks.attach(args, approval), "agent": self.agent_names.get(actor, actor)}
        headers = {"Authorization": f"Bearer {self._keys[actor]}"}
        delay = 0.5
        for attempt in range(8):
            try:
                r = self._http.post(f"{self.base_url}/v1/actions/authorize", json=body, headers=headers)
            except httpx.TransportError:
                if attempt == 7:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 8)
                continue
            if r.status_code != 429:
                break
            time.sleep(delay)
            delay = min(delay * 2, 8)
        r.raise_for_status()
        d = r.json()
        kind, reason = self.hooks.classify(d)
        return Decision(
            actor=actor,
            tool=tool,
            args=dict(args),
            outcome=str(d.get("outcome")),
            kind=kind,
            reason=reason,
            action_id=str(d.get("action_id")),
            record=d.get("record"),
            bound_args=self.hooks.bound_args(d, args),
            approval_id=approval.id if approval else None,
        )


def issuer_key(base_url: str) -> tuple[str, str]:
    """The issuer key a run pins, fetched once at the start. Returns (public_key, key_id)."""
    d = httpx.get(f"{base_url.rstrip('/')}/v1/attestation/public-key", timeout=15).json()
    return str(d["public_key"]), str(d.get("key_id", ""))


def load_adapter(path: str | os.PathLike):
    """Load a deployment adapter module from a file path (kept outside this repository)."""
    p = Path(path).expanduser().resolve()
    spec = importlib.util.spec_from_file_location("arena_seal_adapter", p)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load adapter from {p}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in ("connect",):
        if not hasattr(mod, name):
            raise ImportError(f"adapter {p} has no {name}()")
    return mod


def connect(base_url: str | None = None, adapter_path: str | None = None, **opts) -> Connection:
    """Connect to a Seal deployment through its adapter.

    ARENA_SEAL_URL names the gateway and ARENA_SEAL_ADAPTER the adapter file. The adapter
    creates the organisation's rules, one agent key per actor and the approver's key, and
    returns a Connection. See ARCHITECTURE.md, "Connecting to Seal".
    """
    base_url = base_url or os.environ.get("ARENA_SEAL_URL", "")
    adapter_path = adapter_path or os.environ.get("ARENA_SEAL_ADAPTER", "")
    if not base_url or not adapter_path:
        raise RuntimeError("live runs need ARENA_SEAL_URL and ARENA_SEAL_ADAPTER; replays need neither")
    return load_adapter(adapter_path).connect(base_url, **opts)
