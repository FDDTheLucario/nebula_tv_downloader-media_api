import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Point the global nebula.db at a per-test temp file.

    The database location is resolved from the NEBULA_DB_PATH env var first
    (see utils.paths), so setting it here isolates every test's db and keeps
    the file at ``tmp_path/nebula.db`` for tests that assert on its location.
    """
    monkeypatch.setenv("NEBULA_DB_PATH", str(tmp_path / "nebula.db"))
