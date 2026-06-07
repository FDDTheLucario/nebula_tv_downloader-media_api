from pathlib import Path

from utils import paths


def test_get_db_path_prefers_env(monkeypatch, tmp_path):
    target = tmp_path / "custom.db"
    monkeypatch.setenv(paths.ENV_VAR, str(target))
    assert paths.get_db_path() == target


def test_get_db_path_uses_pointer_when_no_env(monkeypatch, tmp_path):
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    pointer = tmp_path / "pointer"
    db_target = tmp_path / "pointed.db"
    pointer.write_text(str(db_target))
    monkeypatch.setattr(paths, "POINTER_FILE", pointer)
    assert paths.get_db_path() == db_target


def test_get_db_path_default_when_nothing_set(monkeypatch, tmp_path):
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    monkeypatch.setattr(paths, "POINTER_FILE", tmp_path / "missing")
    monkeypatch.setattr(paths, "DEFAULT_DB_PATH", tmp_path / "default.db")
    assert paths.get_db_path() == tmp_path / "default.db"


def test_get_db_path_ignores_empty_pointer(monkeypatch, tmp_path):
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    pointer = tmp_path / "pointer"
    pointer.write_text("   \n")
    monkeypatch.setattr(paths, "POINTER_FILE", pointer)
    monkeypatch.setattr(paths, "DEFAULT_DB_PATH", tmp_path / "default.db")
    assert paths.get_db_path() == tmp_path / "default.db"


def test_set_db_path_writes_pointer(monkeypatch, tmp_path):
    pointer = tmp_path / "nested" / "pointer"
    monkeypatch.setattr(paths, "POINTER_FILE", pointer)
    paths.set_db_path(Path("/some/where/nebula.db"))
    assert pointer.read_text() == "/some/where/nebula.db"
