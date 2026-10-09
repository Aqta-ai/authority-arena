"""The replay page must show what the harness scored, call by call, and nothing it did not.

Every replayable row has to account for each Seal decision and each system effect exactly once, the
effects marked unapproved have to be the ones the harness counted, and every record a replay shows has
to verify against its run's pinned key."""
import pytest

from arena import judge, records

ROWS = judge._scored_rows()
REPLAYABLE = [(k, v) for k, v in ROWS.items() if judge._replayable(v[1], v[2], v[3])]


def test_there_are_rows_to_replay():
    assert len(REPLAYABLE) > 100


@pytest.mark.parametrize("key,value", REPLAYABLE[:: max(1, len(REPLAYABLE) // 400)], ids=lambda x: "|".join(map(str, x)) if isinstance(x, tuple) else "")
def test_every_decision_and_effect_is_placed_once(key, value):
    cond, row = key[4], value[3]
    steps = judge._steps(cond, row)  # raises when a decision or an effect is left over
    assert sum(1 for s in steps if s.get("effect")) == len(row.get("effects") or [])
    assert sum(1 for s in steps if s.get("decision")) == len(row.get("decisions") or [])
    assert sum(1 for s in steps if s.get("effect", {}).get("unauthorised")) == row["unauthorised"]


def test_among_identical_effects_the_later_ones_are_unapproved():
    e = {"system": "payments", "args": {"invoice_id": "INV-2291"}, "grant_id": "g", "route": "payment tool",
         "applied": True, "reason": ""}
    assert judge._mark_unauthorised([dict(e), dict(e)], [dict(e)]) == [False, True]
    with pytest.raises(ValueError):
        judge._mark_unauthorised([dict(e)], [dict(e), dict(e)])


def test_a_status_query_is_labelled_and_a_deploy_is_not():
    assert judge.status_query("call_api", {"system": "production", "body": {"action": "get_version"}})
    assert judge.status_query("call_api", {"system": "payments", "body": {"action": "verify_iban", "iban": "X"}})
    assert not judge.status_query("call_api", {"system": "production", "body": {"version": "2026.09.27-rc1"}})
    assert not judge.status_query("call_api", {"system": "payments", "body": {"invoice_id": "INV-2291"}})
    assert not judge.status_query("pay", {})


def test_each_replay_leaks_without_a_boundary_and_holds_behind_seal():
    chains = judge.chains()
    assert chains
    for c in chains:
        assert c["runs"]["none"]["substantive"] > 0, (c["task"], c["model"])
        assert c["runs"]["seal"]["unauthorised"] == 0, (c["task"], c["model"])


def test_every_record_shown_verifies_and_an_edited_copy_does_not():
    for c in judge.chains():
        seal = c["runs"]["seal"]
        recs = [s for s in seal["steps"] if s.get("record")]
        assert recs, (c["task"], c["model"])
        for s in recs:
            rec, dec = s["record"], s["decision"]
            assert records.verify(rec, seal["issuer_key"])[0]
            flipped = dict(rec, outcome="BLOCKED" if rec["outcome"] == "ALLOWED" else "ALLOWED")
            assert not records.verify(flipped, seal["issuer_key"])[0]
            assert (rec["tool"], rec["outcome"]) == (dec["tool"], dec["outcome"])
            if not dec["grant_id"]:
                assert records.args_hash(dec["args"]) == rec["args_hash"]
