"""ACTION-v1 records as the world's systems see them.

A consequential system in the arena does not take Seal's word for anything at run time.
Before it changes state it checks the record it was handed, the way a stranger would:
with the published verifier (aqta-verify-receipt, profile ACTION-v1) against the pinned
issuer key, and then against the call it is about to run.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Callable, Iterable, Mapping, Optional

import aqta_verify_receipt

MAX_RECORD_AGE_SECONDS = 300


def canonical(value) -> str:
    """Canonical JSON (ACTION-v1 section 6) for the string-only objects the arena declares.

    Keys sort by UTF-16 code unit, there is no whitespace and non-ASCII stays literal.
    Numbers are refused on purpose: every argument in the arena is a string, so the
    number-formatting differences between languages cannot arise.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        raise ValueError("arena arguments are strings; numbers are not used")
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical(v) for v in value) + "]"
    if isinstance(value, Mapping):
        keys = sorted((str(k) for k in value), key=lambda k: k.encode("utf-16-be"))
        return "{" + ",".join(f"{json.dumps(k, ensure_ascii=False)}:{canonical(value[k])}" for k in keys) + "}"
    raise ValueError(f"not canonicalisable: {type(value).__name__}")


def args_hash(args: Mapping) -> str:
    return hashlib.sha256(canonical(args).encode("utf-8")).hexdigest()


def verify(record: object, issuer_key: str) -> tuple[bool, str]:
    """The published verifier, profile ACTION-v1, issuer key pinned."""
    result = aqta_verify_receipt.verify_receipt(record, trusted_public_key=issuer_key, profile="ACTION-v1")
    return bool(result.valid), (result.reason or "")


def refusal(
    record: object,
    *,
    tool: str,
    args: Mapping[str, str],
    bound_args: Optional[Mapping[str, str]],
    issuer_key: str,
    org_id: str,
    spent: Iterable[str],
    reference_keys: Iterable[str] = (),
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    max_age_seconds: int = MAX_RECORD_AGE_SECONDS,
) -> Optional[str]:
    """Why this system will not act on this record, or None when it will.

    `args` is exactly what the system is about to do. `bound_args` is the object the
    record's args_hash commits to (the declared arguments, plus any approval reference
    Seal bound in); when absent the declared arguments are hashed as they are.
    """
    if not isinstance(record, dict):
        return "no Seal record was presented"
    ok, why = verify(record, issuer_key)
    if not ok:
        return f"the record does not verify ({why})"
    if record.get("outcome") != "ALLOWED":
        return f"the record says {record.get('outcome')}, not ALLOWED"
    if record.get("tool") != tool:
        return f"the record clears {record.get('tool')!r}, not {tool!r}"
    if record.get("org_id") != org_id:
        return "the record belongs to another organisation"
    if record.get("action_id") in set(spent):
        return "the record has already been used"
    try:
        issued = datetime.fromisoformat(str(record["timestamp"]))
    except (KeyError, ValueError):
        return "the record's timestamp is unreadable"
    age = (now() - issued).total_seconds()
    if age > max_age_seconds:
        return f"the record is {int(age)} s old; this system accepts {max_age_seconds} s"
    committed = dict(bound_args) if bound_args is not None else dict(args)
    if args_hash(committed) != record.get("args_hash"):
        return "the arguments do not hash to the record's args_hash"
    if any(committed.get(k) != v for k, v in args.items()):
        return "the arguments differ from the ones Seal cleared"
    extra = set(committed) - set(args) - set(reference_keys)
    if extra:
        return "the record commits to arguments this call does not carry"
    return None
