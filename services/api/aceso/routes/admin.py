"""Admin: audit log, tamper check and system status."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from aceso.auth import admin_only, any_role
from aceso.config import settings
from aceso.db import tx
from aceso.privacy import Redactor

router = APIRouter()


@router.get("/admin/audit")
def audit_log(limit: int = 200, user: dict = Depends(admin_only)):
    with tx() as cur:
        cur.execute(
            """select a.id, a.at, a.actor_label, a.actor_role, a.action, a.entity_type, a.entity_id,
                      a.from_state, a.to_state, a.payload, p.mrn
               from audit_log a left join patients p on p.id = a.patient_id
               order by a.id desc limit %s""", (min(limit, 1000),))
        rows = cur.fetchall()
        cur.execute("select count(*) as n from audit_log")
        return {"rows": rows, "total": cur.fetchone()["n"]}


@router.post("/admin/audit/verify")
def verify_chain(user: dict = Depends(admin_only)):
    with tx() as cur:
        cur.execute("select ok, broken_at from verify_audit_chain()")
        return cur.fetchone()


class RedactionPreview(BaseModel):
    text: str = Field(max_length=5000)
    patient_name: str = Field(default="", max_length=120)


@router.post("/privacy/preview")
def redaction_preview(body: RedactionPreview, user: dict = Depends(any_role)):
    """Run the same redactor the pipeline uses on any text. Nothing is stored or sent anywhere."""
    redactor = Redactor([body.patient_name])
    redactor.learn([body.text])
    sent, spans = redactor.apply(body.text)
    return {"sent": sent, "spans": spans, "redacted": dict(redactor.counts)}


@router.get("/status")
def status(user: dict = Depends(any_role)):
    """What the model layer is: shown in the UI so nobody has to guess where data goes."""
    onprem = settings.llm_mode == "onprem"
    return {"llm_mode": settings.llm_mode,
            "llm": f"Ollama · {settings.ollama_model}" if onprem else f"{settings.llm_base_url} · {settings.llm_model}",
            "stt": None if onprem else settings.stt_model,
            "user": {"name": user["full_name"], "role": user["role"]}}
