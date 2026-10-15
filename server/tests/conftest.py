import os
import uuid

import pytest

from canon.graph.db import connect


@pytest.fixture(scope="session")
def db():
    try:
        conn = connect()
        conn.connection.ping()
    except Exception:
        pytest.skip("FalkorDB is not running (docker compose up -d falkordb)")
    return conn


@pytest.fixture(scope="session", autouse=True)
def _throwaway_accounts():
    """Apps built from the environment keep their accounts in a throwaway graph, never `canon_accounts`."""
    name = f"test_canon_accounts_{uuid.uuid4().hex[:12]}"
    saved = {k: os.environ.get(k) for k in ("CANON_ACCOUNTS_GRAPH", "CANON_DEV_LOGIN", "GITHUB_CLIENT_ID")}
    os.environ["CANON_ACCOUNTS_GRAPH"] = name
    os.environ.pop("CANON_DEV_LOGIN", None)
    os.environ.pop("GITHUB_CLIENT_ID", None)
    yield name
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        conn = connect()
        if name in conn.list_graphs():
            conn.select_graph(name).delete()
    except Exception:
        pass


@pytest.fixture
def graph(db):
    """A fresh, uniquely named graph per test, deleted afterwards."""
    g = db.select_graph(f"test_canon_{uuid.uuid4().hex[:12]}")
    yield g
    try:
        g.delete()
    except Exception:
        pass
