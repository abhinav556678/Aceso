"""The database enforces the non-negotiable rules by itself (build guide §5.11)."""
import psycopg
import pytest

from tests.conftest import PATIENTS


@pytest.fixture()
def conn(database):
    with psycopg.connect(database, autocommit=True) as connection:
        yield connection


def act_as(conn, role: str) -> None:
    user_id = conn.execute("select id from profiles where role = %s::user_role", (role,)).fetchone()[0]
    conn.execute("select set_config('request.jwt.claim.sub', %s, false)", (str(user_id),))


def new_fact(conn, state: str = "extracted") -> str:
    return conn.execute("insert into facts(patient_id, fact_type, display, source, state) "
                        "values (%s, 'symptom', 'test symptom', 'manual', %s::fact_state) returning id",
                        (PATIENTS[6], state)).fetchone()[0]


def test_audio_fact_without_a_span_is_rejected(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("insert into facts(patient_id, fact_type, display, source) values (%s, 'symptom', 'x', 'audio')",
                     (PATIENTS[6],))


def test_document_fact_without_a_box_is_rejected(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("insert into facts(patient_id, fact_type, display, source) values (%s, 'symptom', 'x', 'document')",
                     (PATIENTS[6],))


def test_extracted_cannot_jump_to_confirmed(conn):
    act_as(conn, "doctor")
    with pytest.raises(psycopg.errors.RaiseException, match="Illegal fact transition"):
        conn.execute("update facts set state = 'clinician_confirmed' where id = %s", (new_fact(conn),))


def test_only_a_doctor_can_confirm(conn):
    fact_id = new_fact(conn, "verified")
    act_as(conn, "nurse")
    with pytest.raises(psycopg.errors.RaiseException, match="Only a doctor"):
        conn.execute("update facts set state = 'clinician_confirmed' where id = %s", (fact_id,))
    act_as(conn, "doctor")
    conn.execute("update facts set state = 'clinician_confirmed' where id = %s", (fact_id,))
    row = conn.execute("select actor_label, actor_role, from_state, to_state from audit_log "
                       "where entity_id = %s order by id desc limit 1", (fact_id,)).fetchone()
    assert row == ("Dr. Rao", "doctor", "verified", "clinician_confirmed")


def test_audit_log_is_append_only_and_chain_is_intact(conn):
    for statement in ("update audit_log set action = 'tampered'", "delete from audit_log", "truncate audit_log"):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(statement)
    assert conn.execute("select ok from verify_audit_chain()").fetchone()[0] is True


def test_signed_note_is_immutable(conn):
    note_id = conn.execute("select id from soap_notes where status = 'signed' limit 1").fetchone()[0]
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        conn.execute("update soap_notes set plan = '[]'::jsonb where id = %s", (note_id,))
