# TDD Plan — Migrate channel/episode persistence from JSON files to SQLite

**Scope:** Replace `src/utils/db.py` JSON-file storage (`channel.json` + `episodes.json` per
channel directory) with a single SQLite database. Keep public API stable so `src/main.py` and the
rest of the pipeline are untouched.

**Out of scope:** Media files (videos, thumbnails, subtitles, `.nfo`) stay on disk. Only the
*metadata* persistence (`save_channel_info` / `load_channel_info`) moves to SQLite.

---

## Model assignments (per phase)

| Phase | Role | Model | Why |
|-------|------|-------|-----|
| 0 — Plan | Author this plan, fix design decisions, write test specs | **Opus** (`claude-opus-4-8`) | Cross-file reasoning, API-compat judgment, schema design |
| 1 — Implement (RED→GREEN) | Write each test, then minimal code to pass; one TDD cycle per test below | **Haiku** (`claude-haiku-4-5`) | Mechanical, fully specified cycles; cheap + fast |
| 2 — Verify | Run full suite, audit correctness vs. plan, adversarial edge-case review, confirm no regressions in `main.py` flow | **Sonnet** (`claude-sonnet-4-6`) | Stronger review/verification than Haiku, cheaper than Opus |

**Loop:** Phase 1 (Haiku) and Phase 2 (Sonnet) run per cycle. Sonnet returns PASS/FAIL +
findings; on FAIL, Haiku fixes; Opus re-engages only if a design decision is wrong.

Spawn pattern (from main thread):
- `Agent(subagent_type: "general-purpose", model: "haiku", ...)` — implement cycle N
- `Agent(subagent_type: "general-purpose", model: "sonnet", ...)` — verify cycle N

---

## Design (fixed by Opus — Haiku does not redecide these)

### Public API — UNCHANGED signatures (so `main.py` needs no edits)
```python
def save_channel_info(channel_slug, channel_data, episodes_data, output_directory: Path) -> Path
def load_channel_info(channel_slug, output_directory: Path) -> NebulaChannelVideoContentResponseModel
```
- `save_channel_info` STILL creates and returns the per-channel media directory
  (`output_directory / channel_slug`) — `main.py` uses the return value as the download root.
  Only the JSON writes are replaced by SQLite writes.
- DB file location: `output_directory / "nebula.db"` (single DB for all channels).

### Schema
```sql
CREATE TABLE IF NOT EXISTS channels (
    slug          TEXT PRIMARY KEY,
    details_json  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS episodes (
    channel_slug    TEXT NOT NULL,
    slug            TEXT NOT NULL,
    published_year  INTEGER,
    episode_json    TEXT NOT NULL,
    PRIMARY KEY (channel_slug, slug),
    FOREIGN KEY (channel_slug) REFERENCES channels(slug) ON DELETE CASCADE
);
```
- One channel row (full `details.model_dump()` JSON). One row per episode
  (`episode.model_dump()` JSON), `published_year` derived from
  `datetime.fromisoformat(published_at).year` (nullable, for future querying; not required to
  round-trip).
- Use `json.dumps(model_dump(), default=str)` for serialization (matches current `default=str`
  handling of `HttpUrl`/non-native types).

### Behavioral decisions
- **Overwrite semantics:** `save_channel_info` upserts the channel row and **replaces** that
  channel's episode set (delete-then-insert within ONE transaction). Preserves the current
  "save fully rewrites metadata" behavior. Other channels' rows untouched.
- **`next` / `previous`:** not persisted. `load_channel_info` reconstructs the envelope with
  `next=None, previous=None` (identical to current behavior).
- **Connection helper:** module-private `_connect(output_directory) -> sqlite3.Connection` that
  ensures parent dir exists, opens `nebula.db`, runs `PRAGMA foreign_keys = ON`, and bootstraps
  schema via `CREATE TABLE IF NOT EXISTS`. Caller closes (use `with closing(...)` or try/finally).
- **Not-found error:** introduce `class ChannelNotFoundError(LookupError)` in `db.py`, raised by
  `load_channel_info` with the slug in the message. (`main.py` does not catch the old
  `FileNotFoundError`, so this is safe.) Drop the old `FileNotFoundError`/`CHANNEL_FILENAME`/
  `EPISODES_FILENAME` constants.
- **Corrupt stored data:** if a row's JSON fails to parse or fails Pydantic validation,
  `load_channel_info` propagates the raised error (no silent recovery).

### Module shape (`src/utils/db.py` after refactor)
```python
import json, sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

DB_FILENAME = "nebula.db"

class ChannelNotFoundError(LookupError): ...

def _connect(output_directory: Path) -> sqlite3.Connection: ...
def save_channel_info(...) -> Path: ...
def load_channel_info(...) -> NebulaChannelVideoContentResponseModel: ...
```

---

## TDD cycles (RED → GREEN, one per row; Haiku implements, Sonnet verifies)

Run via `pipenv run pytest tests/utils/test_db.py`. Each cycle: write the test (RED, must fail
for the right reason), then minimal code to pass (GREEN), then run the whole file.

| # | Test name | Asserts | New code unlocked |
|---|-----------|---------|-------------------|
| 1 | `test_connect_creates_db_file_and_schema` | `_connect` creates `output_directory/nebula.db`; `channels` + `episodes` tables exist (query `sqlite_master`) | `_connect`, schema bootstrap |
| 2 | `test_save_creates_channel_directory_and_returns_it` | returns `tmp_path/"ch-slug"`, which `is_dir()` | dir creation + return value |
| 3 | `test_save_writes_channel_row` | `channels` has 1 row, `slug == "ch-slug"`, `details_json` parses to dict with `slug` | channel upsert |
| 4 | `test_save_writes_one_row_per_episode` | `episodes` count == number passed; each `episode_json` parses; `published_year` populated | episode insert |
| 5 | `test_save_empty_episode_list` | save with `_episodes()` (no results) → 0 episode rows, channel row present | empty-set handling |
| 6 | `test_save_then_load_roundtrip` | load returns details (`title`), `len(results)==1`, episode `title`, `next is None`, `previous is None` | `load_channel_info` |
| 7 | `test_save_overwrites_replaces_episode_set` | save 2 eps, re-save 1 ep → load returns exactly 1 (no stale rows) | delete-then-insert txn |
| 8 | `test_save_preserves_unrelated_files_in_channel_dir` | pre-existing `video.mp4` in channel dir survives a save | non-destructive dir handling |
| 9 | `test_save_two_channels_are_isolated` | saving `ch-a` then `ch-b`; loading `ch-a` unaffected by `ch-b` episodes | per-channel scoping |
| 10 | `test_load_missing_channel_raises_ChannelNotFoundError` | `pytest.raises(ChannelNotFoundError)`, slug in message | not-found path |
| 11 | `test_load_empty_episode_set_returns_empty_results` | channel saved with no episodes → `results == []` | empty load |
| 12 | `test_load_corrupt_episode_json_raises` | manually corrupt an `episode_json` cell → load raises (json/validation error) | error propagation |
| 13 | `test_roundtrip_preserves_nested_model_fields` | deep field survives (e.g. `results[0].images.thumbnail.src`, `attributes`) — guards `default=str` HttpUrl serialization | serialization fidelity |
| 14 | `test_save_is_atomic_on_failure` | inject a failing insert mid-save → channel's prior committed state intact (no half-written episode set) | transaction wrapping |

**Fixtures:** reuse existing helpers in `tests/utils/test_db.py` — `_channel()`, `_episode()`,
`_episodes()` (built from `tests/models/nebula/test_channel.py::_channel_payload` and
`test_episode.py::_episode_payload`). Drop imports of `CHANNEL_FILENAME` / `EPISODES_FILENAME` /
`json`-file assertions; replace file-read assertions with direct `sqlite3` queries against
`tmp_path/"nebula.db"`.

---

## Verification checklist (Phase 2 — Sonnet)

1. `pipenv run pytest tests/utils/test_db.py` — all green.
2. `pipenv run pytest` — full suite green; confirm no other module imported the removed
   `CHANNEL_FILENAME` / `EPISODES_FILENAME` / `FileNotFoundError` contract
   (`grep -rn "CHANNEL_FILENAME\|EPISODES_FILENAME" src tests`).
3. `pipenv run ruff check src tests` clean.
4. Trace `main.py`: `save_channel_info` return value still drives
   `create_directory_structure_for_channel` / download paths; `load_channel_info` still returns a
   valid `NebulaChannelVideoContentResponseModel` when `load_channel_data_from_db` is set.
5. Adversarial: concurrent-save not required (tool is single-threaded by design — README), but
   confirm connections are closed (no leaked file handles on Windows/`tmp_path` cleanup), and
   `PRAGMA foreign_keys = ON` actually set per-connection.
6. Confirm round-trip equality of a fully-populated model (not just sampled fields).

## Definition of done
- `utils/db.py` uses only `sqlite3` for metadata; no `channel.json`/`episodes.json` writes remain.
- Public signatures unchanged; `main.py` unmodified.
- All 14 cycles green + full suite green + ruff clean.
- `README.md` "Output layout" note updated if metadata location is user-visible (DB at
  `<download_path>/nebula.db`); update `CLAUDE.md` db-layer description.
