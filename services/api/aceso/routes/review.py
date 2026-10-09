"""Human-in-the-loop: fact review, alert handling and encounter sign-off (doctor only where it matters)."""
import hashlib
import json
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from aceso import soap
from aceso.auth import clinical, doctor_only
from aceso.db import audit, tx
from aceso.safety import engine

router = APIRouter()

NEVER_COLLAPSE = ("allergy", "medication")
FOLLOW_UP = re.compile(r"(repeat|recheck|review|follow[- ]?up|test)\b(.*?)\bin\s+(\d+)\s*(day|week|month)s?", re.I)
DAYS = {"day": 1, "week": 7, "month": 30}


class Reason(BaseModel):
    reason: str = Field(min_length=10, description="Why (at least 10 characters) - written to the audit log")


class Resolution(BaseModel):
    keep_fact_id: str
    reason: str = Field(min_length=10)


def _fact(cur, fact_id: str) -> dict:
    cur.execute("select id, patient_id, encounter_id, state::text as state, display from facts where id = %s for update",
                (fact_id,))
    fact = cur.fetchone()
    if not fact:
        raise HTTPException(404, "Fact not found")
    return fact


def _after_change(cur, fact: dict) -> None:
    """Any fact state change re-runs the safety engine and rebuilds the draft note."""
    engine.evaluate(cur, fact["patient_id"], fact["encounter_id"])
    if fact["encounter_id"]:
        soap.regenerate(cur, fact["encounter_id"])


def confirm_fact(cur, fact: dict) -> None:
    """extracted -> verified -> clinician_confirmed; the DB trigger rejects anyone but a doctor."""
    if fact["state"] == "extracted":
        cur.execute("update facts set state = 'verified', needs_attention = false where id = %s", (fact["id"],))
    cur.execute("update facts set state = 'clinician_confirmed', needs_attention = false where id = %s", (fact["id"],))


@router.post("/facts/{fact_id}/confirm")
def confirm(fact_id: str, user: dict = Depends(doctor_only)):
    with tx(user) as cur:
        fact = _fact(cur, fact_id)
        if fact["state"] not in ("extracted", "verified"):
            raise HTTPException(409, f"A {fact['state']} fact cannot be confirmed.")
        confirm_fact(cur, fact)
        _after_change(cur, fact)
    return {"id": fact_id, "state": "clinician_confirmed"}


@router.post("/facts/{fact_id}/reject")
def reject(fact_id: str, user: dict = Depends(clinical)):
    with tx(user) as cur:
        fact = _fact(cur, fact_id)
        if fact["state"] not in ("extracted", "verified"):
            raise HTTPException(409, f"A {fact['state']} fact cannot be rejected.")
        cur.execute("update facts set state = 'rejected', needs_attention = false where id = %s", (fact_id,))
        _after_change(cur, fact)
    return {"id": fact_id, "state": "rejected"}


def _alert(cur, alert_id: str) -> dict:
    cur.execute("select * from safety_alerts where id = %s for update", (alert_id,))
    alert = cur.fetchone()
    if not alert:
        raise HTTPException(404, "Alert not found")
    if alert["status"] != "open":
        raise HTTPException(409, f"Alert is already {alert['status']}.")
    return alert


def _close_alert(cur, alert: dict, status: str, reason: str, user: dict) -> None:
    cur.execute("update safety_alerts set status = %s::alert_status, override_reason = %s, resolved_by = %s, "
                "resolved_at = now() where id = %s", (status, reason, user["id"], alert["id"]))
    audit(cur, f"alert.{status}", "safety_alert", alert["id"], alert["patient_id"],
          {"rule_id": alert["rule_id"], "reason": reason}, user, from_state="open", to_state=status)


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: str, body: Reason, user: dict = Depends(doctor_only)):
    with tx(user) as cur:
        _close_alert(cur, _alert(cur, alert_id), "acknowledged", body.reason, user)
    return {"id": alert_id, "status": "acknowledged"}


@router.post("/alerts/{alert_id}/override")
def override(alert_id: str, body: Reason, user: dict = Depends(doctor_only)):
    with tx(user) as cur:
        _close_alert(cur, _alert(cur, alert_id), "overridden", body.reason, user)
    return {"id": alert_id, "status": "overridden"}


@router.post("/alerts/{alert_id}/resolve")
def resolve_contradiction(alert_id: str, body: Resolution, user: dict = Depends(doctor_only)):
    """The doctor picks which of two contradicting facts is true; the other is superseded."""
    with tx(user) as cur:
        alert = _alert(cur, alert_id)
        ids = [str(i) for i in alert["trigger_fact_ids"]]
        if alert["rule_id"] != "RECORD-CONTRADICTION" or body.keep_fact_id not in ids:
            raise HTTPException(400, "Choose one of the two contradicting facts to keep.")
        kept = _fact(cur, body.keep_fact_id)
        if kept["state"] in ("extracted", "verified"):
            confirm_fact(cur, kept)
        for other in ids:
            if other != body.keep_fact_id:
                cur.execute("update facts set state = 'superseded', superseded_by = %s where id = %s",
                            (body.keep_fact_id, other))
        _close_alert(cur, alert, "resolved", body.reason, user)
        _after_change(cur, kept)
    return {"id": alert_id, "status": "resolved"}


def sign_blockers(cur, encounter: dict) -> list[str]:
    """The four gating rules, re-checked on the server."""
    cur.execute("select fact_type::text as fact_type, state::text as state, attention_reasons from facts "
                "where encounter_id = %s and state in ('extracted','verified')", (encounter["id"],))
    facts = cur.fetchall()
    unreviewed = [f for f in facts if f["state"] == "extracted"]
    omissions = [f for f in unreviewed if "possible_omission" in (f["attention_reasons"] or [])]
    never_collapse = [f for f in facts if f["state"] == "verified" and f["fact_type"] in NEVER_COLLAPSE]
    cur.execute("select count(*) as n from safety_alerts where patient_id = %s and status = 'open' "
                "and severity in ('critical','high')", (encounter["patient_id"],))
    alerts = cur.fetchone()["n"]
    blockers = []
    if len(unreviewed) > len(omissions):
        blockers.append(f"{len(unreviewed) - len(omissions)} unverified fact(s) need to be confirmed or rejected")
    if omissions:
        blockers.append(f"{len(omissions)} possible omission(s) need to be confirmed or rejected")
    if never_collapse:
        blockers.append(f"{len(never_collapse)} allergy/medication fact(s) need explicit confirmation")
    if alerts:
        blockers.append(f"{alerts} critical/high alert(s) need to be acknowledged or overridden with a reason")
    return blockers


@router.get("/encounters/{encounter_id}/sign-check")
def sign_check(encounter_id: str, user: dict = Depends(clinical)):
    with tx() as cur:
        cur.execute("select * from encounters where id = %s", (encounter_id,))
        encounter = cur.fetchone()
        if not encounter:
            raise HTTPException(404, "Encounter not found")
        return {"status": encounter["status"], "blockers": sign_blockers(cur, encounter)}


@router.post("/encounters/{encounter_id}/sign")
def sign(encounter_id: str, user: dict = Depends(doctor_only)):
    """One transaction: confirm remaining verified facts, lock the note, open follow-up loops, audit."""
    with tx(user) as cur:
        cur.execute("select * from encounters where id = %s for update", (encounter_id,))
        encounter = cur.fetchone()
        if not encounter:
            raise HTTPException(404, "Encounter not found")
        if encounter["status"] == "signed":
            raise HTTPException(409, "This encounter is already signed.")
        blockers = sign_blockers(cur, encounter)
        if blockers:
            raise HTTPException(409, {"message": "Cannot sign off yet.", "blockers": blockers})

        cur.execute("update facts set state = 'clinician_confirmed' where encounter_id = %s and state = 'verified' "
                    "returning id", (encounter_id,))
        bulk_confirmed = cur.rowcount
        note = soap.regenerate(cur, encounter_id) or {}
        content_hash = hashlib.sha256(json.dumps(note, sort_keys=True).encode()).hexdigest()
        cur.execute("update soap_notes set status = 'signed', signed_by = %s, signed_at = now(), content_hash = %s "
                    "where encounter_id = %s returning id", (user["id"], content_hash, encounter_id))
        note_row = cur.fetchone()
        cur.execute("update encounters set status = 'signed', ended_at = now(), doctor_id = %s where id = %s",
                    (user["id"], encounter_id))

        cur.execute("select id, display from facts where encounter_id = %s and fact_type = 'plan_item' "
                    "and state = 'clinician_confirmed' and assertion = 'present'", (encounter_id,))
        loops = 0
        for plan in cur.fetchall():
            match = FOLLOW_UP.search(plan["display"])
            if not match:
                continue
            due = encounter["started_at"].date() + timedelta(days=int(match.group(3)) * DAYS[match.group(4).lower()])
            cur.execute("insert into open_loops(patient_id, encounter_id, fact_id, description, due_date) "
                        "select %s, %s, %s, %s, %s where not exists (select 1 from open_loops where fact_id = %s)",
                        (encounter["patient_id"], encounter_id, plan["id"], plan["display"], due, plan["id"]))
            loops += cur.rowcount
        audit(cur, "note.sign", "encounter", encounter_id, encounter["patient_id"],
              {"note_id": str(note_row["id"]) if note_row else None, "content_hash": content_hash,
               "facts_bulk_confirmed": bulk_confirmed, "open_loops_created": loops}, user,
              from_state=encounter["status"], to_state="signed")
    return {"status": "signed", "content_hash": content_hash, "facts_bulk_confirmed": bulk_confirmed,
            "open_loops_created": loops}
