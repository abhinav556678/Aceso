"""Tests run against a real Postgres, never a mocked pool.

A throwaway embedded Postgres (pgserver) is started per test session, the real
migrations and seed are applied, and the six demo scenarios are pushed through
the pipeline. Set TEST_DATABASE_URL to use another empty database instead.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))


def pytest_configure(config):
    config.addinivalue_line("markers", "db: needs the test database")


@pytest.fixture(scope="session")
def database(tmp_path_factory):
    url = os.environ.get("TEST_DATABASE_URL")
    server = None
    if not url:
        pytest.importorskip("pgserver", reason="pip install pgserver to run database tests")
        import local_db
        server = local_db.start(tmp_path_factory.mktemp("pg"))
        url = server.get_uri()
    os.environ["SUPABASE_DB_URL"] = url
    # settings may already be loaded (test collection imports aceso), so point it here explicitly
    from aceso.config import settings
    settings.supabase_db_url = url
    settings.demo_role_header = True  # tests name the role per request instead of signing in
    setup =subprocess.run([sys.executable, str(ROOT / "scripts" / "setup_db.py"), "--s1-labs-preloaded"],
                           capture_output=True, text=True, env=os.environ.copy())
    assert setup.returncode == 0, setup.stdout + setup.stderr
    yield url
    from aceso.db import close_pool
    close_pool()
    if server is not None:
        server.cleanup()


@pytest.fixture(scope="session")
def client(database):
    from fastapi.testclient import TestClient

    from aceso.main import app
    with TestClient(app) as test_client:
        yield test_client


def as_role(role: str) -> dict:
    return {"X-Demo-Role": role}


PATIENTS = {n: f"00000000-0000-4000-8000-00000000000{n}" for n in range(1, 7)}
