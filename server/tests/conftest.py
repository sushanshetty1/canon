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


@pytest.fixture
def graph(db):
    """A fresh, uniquely named graph per test, deleted afterwards."""
    g = db.select_graph(f"test_canon_{uuid.uuid4().hex[:12]}")
    yield g
    try:
        g.delete()
    except Exception:
        pass
