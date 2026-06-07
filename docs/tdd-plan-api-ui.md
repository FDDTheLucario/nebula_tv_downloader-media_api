# TDD Plan — Web API + UI + Scheduler (TubeArchivist-style)

Author: Opus (plan). Implement: Haiku. Verify: Sonnet.

## Goal

Add a self-hosted web service on top of the existing archiver:

- **Periodic poll**: every N hours, ask Nebula for each configured channel's videos,
  discover episodes not yet downloaded, enqueue download jobs.
- **Worker**: background thread drains the job queue, runs the existing
  `download_episode` pipeline (thumbnail → video → subs → `.nfo`).
- **API**: FastAPI JSON endpoints + a server-rendered htmx dashboard.
- **No new download logic** — reuse `main.py` / `utils` helpers. This layer only
  *schedules*, *queues*, *tracks*, and *exposes* the existing pipeline.

This is a legal feature (Nebula permits subscribers to archive). We are streamlining it.

## Hard rules

- **All commands via `pipenv run`.** Bare python fails (missing deps).
- `pytest.ini` sets `pythonpath = src . tests`. Import app modules WITHOUT `src.`
  prefix: `from utils.jobs_db import ...`, `from api.service import ...`,
  `from api.app import create_app`.
- Run `pipenv run pytest` from repo root.
- Tests mock HTTP / downloads (`pytest-mock`, monkeypatch). **No real network, no
  real yt-dlp, no real Nebula calls in tests.**
- TDD per module: write the test(s) first (red), implement to green, refactor.
  Run that module's test file after each cycle; run the FULL suite at module end.
- Keep the existing 120 tests passing. Do not break public signatures in
  `utils/db.py`, `main.py`, `config/`.
- No AI co-author trailer in any commit.
- Test tree mirrors src: new tests under `tests/api/` and `tests/utils/`.
- New package needs `src/api/__init__.py` (empty).

## Deps (already installed — do NOT re-run)

`fastapi`, `uvicorn[standard]`, `jinja2`, `apscheduler`, `httpx`, `python-multipart`
are in the Pipfile and virtualenv. `from fastapi.testclient import TestClient` works.

---

## Module 1 — `src/utils/jobs_db.py` (job queue + key/value state)

Persist into the SAME SQLite file as the rest (`<download_path>/nebula.db`,
`DB_FILENAME = "nebula.db"`). Add two new tables alongside the existing
`channels` / `episodes` tables (separate `_connect` is fine — both create-if-not-exists
in the same file).

### Schema

```sql
CREATE TABLE IF NOT EXISTS download_jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_slug  TEXT NOT NULL,
    episode_slug  TEXT NOT NULL,
    episode_json  TEXT NOT NULL,
    state         TEXT NOT NULL DEFAULT 'queued',   -- queued|running|done|failed
    error         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    UNIQUE(channel_slug, episode_slug)
);
CREATE TABLE IF NOT EXISTS app_state (
    key    TEXT PRIMARY KEY,
    value  TEXT
);
```

### Public API (all take `output_directory: Path` first, like `utils/db.py`)

- `_connect(output_directory) -> sqlite3.Connection` — mkdir, open nebula.db, create
  both tables, `row_factory = sqlite3.Row`, return conn.
- `enqueue_job(output_directory, channel_slug, episode_slug, episode_json: str) -> bool`
  — insert a `queued` job. Idempotent on `(channel_slug, episode_slug)`:
  if no row exists → insert, return `True`.
  if existing row state is `failed` → reset to `queued`, clear `error`, bump
  `updated_at`, return `True` (retry).
  if existing state is `queued`/`running`/`done` → leave untouched, return `False`.
- `claim_next_job(output_directory) -> dict | None` — atomically pick the oldest
  `queued` job and flip it to `running`. Use `BEGIN IMMEDIATE`; SELECT id WHERE
  state='queued' ORDER BY id LIMIT 1; UPDATE that id → running + updated_at; COMMIT.
  Return the job as a dict (post-update state `running`), or `None` if none queued.
- `mark_job_done(output_directory, job_id) -> None` — state='done', updated_at.
- `mark_job_failed(output_directory, job_id, error: str) -> None` — state='failed',
  error=error, updated_at.
- `requeue_job(output_directory, job_id) -> bool` — if job exists and state in
  {failed, done}: set queued, clear error, bump updated_at, return True; else False.
- `reset_running_jobs(output_directory) -> int` — set every `running` job back to
  `queued` (crash recovery on startup), return count reset.
- `list_jobs(output_directory, state: str | None = None, limit: int = 200) -> list[dict]`
  — newest first (`ORDER BY id DESC`), optional state filter.
- `get_job(output_directory, job_id) -> dict | None`.
- `count_jobs_by_state(output_directory) -> dict[str, int]` — always include all four
  keys queued/running/done/failed (default 0).
- `set_state(output_directory, key, value: str) -> None` — upsert into app_state.
- `get_state(output_directory, key) -> str | None`.

Dict shape from `_row_to_dict`: `{id, channel_slug, episode_slug, episode_json, state,
error, created_at, updated_at}`. Timestamps: `datetime.now().isoformat()` via a
`_now()` helper (so tests can monkeypatch it if needed).

### Tests — `tests/utils/test_jobs_db.py` (use `tmp_path`)

1. `test_connect_creates_jobs_tables` — both tables exist in sqlite_master.
2. `test_enqueue_new_job_returns_true_and_persists` — returns True; `list_jobs` has 1
   row, state `queued`, correct slugs/json.
3. `test_enqueue_duplicate_queued_returns_false` — second enqueue of same
   channel+episode returns False; still 1 row.
4. `test_enqueue_resets_failed_job_to_queued` — enqueue, claim, mark_failed, enqueue
   again → True, state back to `queued`, error cleared.
5. `test_enqueue_done_job_not_reenqueued` — done job: second enqueue returns False,
   stays `done`.
6. `test_claim_next_job_returns_oldest_and_marks_running` — enqueue 2; claim returns
   first by id, its state is `running`.
7. `test_claim_next_job_none_when_empty` — returns None on empty / no queued.
8. `test_claim_skips_running_and_done` — only queued are claimable.
9. `test_mark_job_done` / `test_mark_job_failed` — state + error set correctly.
10. `test_requeue_failed_job` — failed → queued True; clears error.
11. `test_requeue_nonexistent_returns_false`.
12. `test_reset_running_jobs` — 2 running → reset returns 2, both queued.
13. `test_list_jobs_filter_by_state` — mix; filter returns only matching.
14. `test_count_jobs_by_state` — returns dict with all four keys, correct counts.
15. `test_set_and_get_state_roundtrip` + `test_get_state_missing_returns_none` +
    `test_set_state_upsert_overwrites`.

---

## Module 2 — `src/api/service.py` (orchestration, reuses existing helpers)

Thin glue between Nebula clients, the existing `main.py` helpers, and `jobs_db`.
Inject collaborators as keyword args with real defaults so tests can substitute.

Imports to reuse:
`from nebula_api.channel_videos import get_channel_video_content`
`from nebula_api.video_feed import get_all_channels_slugs_from_video_feed`
`from utils.filtering import filter_out_episodes`
`from utils.db import save_channel_info`
`from main import download_episode`
`from utils import jobs_db`
`from models.nebula.episode import NebulaChannelVideoContentEpisodeResult`
`from models.nebula.video_attributes import VideoNebulaAttributes`

### Functions

- `episode_nfo_path(download_path: Path, channel_slug: str, episode) -> Path`
  — replicate `main.py`'s season logic: `"Specials"` if
  `VideoNebulaAttributes.IS_NEBULA_ORIGINAL in episode.attributes` else
  `f"Season {year}"` where year = `datetime.fromisoformat(episode.published_at).year`.
  Return `download_path/channel_slug/<season>/<slug>/<slug>.nfo`. (No mkdir, no IO.)

- `find_new_episodes(download_path, channel_slug, content, filter_settings) -> list[episode]`
  — `filter_out_episodes(filter_settings, content.episodes.results)`, then keep only
  episodes whose `episode_nfo_path(...)` does NOT exist. Return list.

- `check_channel(channel_slug, config, auth, *, fetch=get_channel_video_content) -> int`
  — `content = fetch(channel_slug=channel_slug, authorization_header=auth.get_authorization_header(full=True))`;
  `save_channel_info(channel_slug, content.details, content.episodes, config.downloader.download_path)`;
  `new = find_new_episodes(config.downloader.download_path, channel_slug, content, config.nebula_filters)`;
  for each ep: `jobs_db.enqueue_job(download_path, channel_slug, ep.slug, ep.model_dump_json())`,
  count the True returns; `jobs_db.set_state(download_path, f"last_check:{channel_slug}", _now())`;
  return enqueued count.

- `resolve_channels(config, auth, *, feed=get_all_channels_slugs_from_video_feed) -> list[str]`
  — if `config.nebula_filters.channels_to_parse` truthy return it, else call `feed(...)`
  (mirror `main.py` args: `authorization_header=auth.get_authorization_header(full=True)`,
  `category_feed_selector=config.nebula_filters.category_search`,
  `cursor_times_limit_fetch_maximum=1`).

- `check_all_channels(config, auth) -> dict[str, int]`
  — channels = `resolve_channels(...)`; result = {ch: check_channel(ch, config, auth)
  for ch in channels}; `jobs_db.set_state(download_path, "last_check", _now())`;
  return result.

- `process_job(job: dict, config, auth, *, downloader=download_episode) -> None`
  — `episode = NebulaChannelVideoContentEpisodeResult(**json.loads(job["episode_json"]))`;
  `channel_dir = config.downloader.download_path / job["channel_slug"]`;
  `channel_dir.mkdir(parents=True, exist_ok=True)`;
  `downloader(job["channel_slug"], channel_dir, episode, auth)`.

`_now()` helper = `datetime.now().isoformat()`.

### Tests — `tests/api/test_service.py`

Use `config` + `fake_auth` fixtures from `tests/api/conftest.py` (Module 5). Build
episodes with the existing `_episode_payload` factory
(`from tests.models.nebula.test_episode import _episode_payload`) and channel content
with `_channel_payload`.

1. `test_episode_nfo_path_specials_for_original` — episode with IS_NEBULA_ORIGINAL →
   path contains `/Specials/`.
2. `test_episode_nfo_path_season_for_regular` — regular episode → `/Season <year>/`,
   year from published_at.
3. `test_find_new_episodes_returns_only_missing_nfo` — create the nfo file on disk for
   one episode (via `episode_nfo_path`, mkdir parents, touch); `find_new_episodes`
   excludes it, includes the other.
4. `test_find_new_episodes_applies_filters` — filter_settings excluding a type drops it.
5. `test_check_channel_enqueues_new_episodes` — stub `fetch` returning a
   `NebulaChannelVideoContentResponseModel` with 2 episodes; assert returns 2 and
   `jobs_db.list_jobs` has 2 queued; assert `save_channel_info` persisted the channel
   (channels table / `utils.db.load_channel_info` works).
6. `test_check_channel_skips_already_downloaded` — pre-create one episode's nfo →
   returns 1, only the other enqueued.
7. `test_check_channel_sets_last_check_state` — `get_state("last_check:<slug>")` set.
8. `test_check_channel_idempotent_second_run_enqueues_zero` — run twice without
   creating nfos → first run N, second run 0 (jobs already queued).
9. `test_resolve_channels_uses_config_list` — config with channels_to_parse → returns
   it, `feed` NOT called (pass a feed stub that raises if called).
10. `test_resolve_channels_falls_back_to_feed` — config channels_to_parse None →
    returns feed stub's value.
11. `test_check_all_channels_aggregates` — monkeypatch `service.check_channel` to a
    stub; assert dict aggregation + global `last_check` set.
12. `test_process_job_invokes_downloader_with_episode` — pass a spy `downloader`;
    assert called once with (channel_slug, channel_dir, episode-with-matching-slug, auth)
    and channel_dir created.
13. `test_process_job_reconstructs_episode_from_json` — episode_json round-trips to a
    model with the right slug/title.

---

## Module 3 — `src/api/worker.py` (background download worker)

```python
class DownloadWorker:
    def __init__(self, config, auth, *, poll_interval: float = 2.0,
                 process=service.process_job): ...
    def run_once(self) -> bool:        # claim one job, process, mark done/failed.
    def start(self) -> None:           # spawn daemon thread looping run_once
    def stop(self, timeout: float = 5.0) -> None:
    @property
    def running(self) -> bool: ...
```

- `run_once`: `job = jobs_db.claim_next_job(download_path)`; if None return False;
  try `self._process(job, self.config, self.auth)` then `jobs_db.mark_job_done(...,
  job["id"])`; except Exception as e → `jobs_db.mark_job_failed(..., job["id"], str(e))`;
  return True. (Always returns True if a job was claimed, even on failure.)
- Thread loop: `while not self._stop.is_set(): if not self.run_once():
  self._stop.wait(self.poll_interval)`. Daemon thread, `threading.Event` for stop.
- Each `run_once` opens its own sqlite connection inside jobs_db calls (already does) —
  thread-safe.

### Tests — `tests/api/test_worker.py`

1. `test_run_once_no_jobs_returns_false` — empty queue → False.
2. `test_run_once_processes_and_marks_done` — enqueue 1; inject `process` spy that does
   nothing; run_once → True; job state `done`; spy called once with the claimed job.
3. `test_run_once_marks_failed_on_exception` — inject `process` that raises
   `RuntimeError("boom")`; run_once True; job state `failed`, error contains "boom".
4. `test_run_once_processes_one_at_a_time` — enqueue 2; two run_once calls → both done,
   process called twice.
5. `test_start_then_stop_drains_queue` — enqueue 2; `start()`; poll until
   `count_jobs_by_state` done==2 (timeout ~5s using small poll_interval like 0.05);
   `stop()`; assert `worker.running is False`. (Use a fast `process` spy. Guard with a
   loop+timeout; do NOT sleep blindly.)

---

## Module 4 — `src/api/scheduler.py` (APScheduler wrapper)

```python
from apscheduler.schedulers.background import BackgroundScheduler

class CheckScheduler:
    def __init__(self, config, auth, *, interval_hours: int = 1,
                 check=service.check_all_channels,
                 scheduler_factory=BackgroundScheduler): ...
    def start(self) -> None:      # add interval job -> self._run, scheduler.start()
    def shutdown(self) -> None:   # scheduler.shutdown(wait=False) if running
    def trigger_now(self) -> dict[str, int]:   # call self._check(config, auth) NOW, return its result
    @property
    def running(self) -> bool: ...
    @property
    def next_run_time(self): ...  # the job's next_run_time or None
    def _run(self) -> None:       # wrapper that calls self._check(config,auth), logs, swallows exceptions
```

- `start`: `self._scheduler = scheduler_factory(); self._scheduler.add_job(self._run,
  "interval", hours=self.interval_hours, id="check_channels"); self._scheduler.start()`.
- `trigger_now`: directly invoke `self._check(self.config, self.auth)` and return result
  (does NOT require scheduler started — used by the "Check now" button).

### Tests — `tests/api/test_scheduler.py`

Avoid starting real timers where possible.
1. `test_trigger_now_calls_check_and_returns_result` — inject `check` stub returning
   `{"ch": 3}`; `trigger_now()` returns it; stub called with (config, auth).
2. `test_start_registers_interval_job` — inject a fake `scheduler_factory` (Mock) →
   assert `add_job` called with trigger `"interval"` and `hours=interval_hours`, and
   `start()` called; `running` True.
3. `test_shutdown_stops_scheduler` — with fake scheduler, `shutdown()` calls
   `scheduler.shutdown`; `running` False after.
4. `test_run_swallows_check_exception` — inject `check` that raises; `_run()` must not
   propagate (no exception escapes).

---

## Module 5 — `src/api/app.py` (FastAPI factory + routes + templates) and conftest

### `tests/api/conftest.py` (write FIRST — fixtures other modules use)

- `__init__.py` in `tests/api/` (empty).
- Fixture `config(tmp_path)`: write a minimal INI to `tmp_path/config.ini` and return
  `Config(tmp_path/config.ini)`. Sections/keys must match `config/config.py` exactly:
  ```ini
  [nebula_api]
  user_api_token = "test-token"
  authorization_header = "preset-header"
  user_agent = "test-agent"
  token_refresh_interval_hours = 6
  [nebula_filters]
  category_search = false
  include_nebula_first = true
  include_nebula_plus = true
  include_nebula_originals = true
  include_regular_videos = true
  channels_to_parse = "ch-slug"
  [downloader]
  download_path = "<tmp_path>/media"
  load_channel_data_from_db = false
  skip_if_video_exists = true
  check_interval_hours = 1
  ```
  Set `download_path` to `str(tmp_path / "media")`. `authorization_header` is preset so
  no auth network call is needed anywhere.
- Fixture `fake_auth`: a simple object (or `types.SimpleNamespace` / Mock) with
  `get_authorization_header(full=False) -> "Bearer test"` and
  `refresh_authorization_token() -> None`.
- Helper to build a `NebulaChannelVideoContentResponseModel` from
  `_channel_payload` + N `_episode_payload`s, exposed as a fixture or function
  `make_content(*episodes)`.

> Config change required (Module 5a): add `check_interval_hours: int = 1` to
> `ConfigurationDownloaderModel` (default 1 hour) and parse it in `config/config.py`
> with a fallback:
> `check_interval_hours=int(config_original.get("downloader","check_interval_hours")) if config_original.has_option("downloader","check_interval_hours") else 1`.
> Add the key to `config.example.ini` (`check_interval_hours = 1`). This keeps existing
> `config.ini`/tests valid (field has a default). Add ONE test in `tests/test_config.py`
> (or existing config file) asserting the default (1) and a parsed override — match that
> file's existing style.

### `create_app(config, auth, *, start_background: bool = True) -> FastAPI`

- `templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))`.
- Store on `app.state`: config, auth, and (if start_background) a `DownloadWorker` and
  `CheckScheduler`.
- Lifespan/startup (only when `start_background`):
  `jobs_db.reset_running_jobs(download_path)`; `worker.start()`;
  `scheduler = CheckScheduler(config, auth, interval_hours=config.downloader.check_interval_hours)`;
  `scheduler.start()`. Shutdown: `worker.stop()`, `scheduler.shutdown()`.
  Use a FastAPI `lifespan` context. When `start_background=False`, do none of this
  (tests use this path).
- Routes (download_path = `config.downloader.download_path`):
  - `GET /healthz` → `{"status": "ok"}`.
  - `GET /api/status` → `{"counts": count_jobs_by_state(...), "last_check":
    get_state("last_check"), "scheduler_running": <bool>}`. (scheduler_running False
    when start_background=False / no scheduler.)
  - `GET /api/channels` → list of channel slugs from the channels table. Add a tiny
    helper `list_channel_slugs(download_path) -> list[str]` in `utils/db.py`
    (SELECT slug FROM channels ORDER BY slug; return []). (Add a db test for it.)
  - `GET /api/jobs?state=` → `list_jobs(download_path, state)` as JSON.
  - `POST /api/check` → run a check now. Use the scheduler's `trigger_now()` if a
    scheduler exists, else call `service.check_all_channels(config, auth)` directly.
    Return `{"enqueued": <dict>}`. (Tests monkeypatch `service.check_all_channels`.)
  - `POST /api/jobs/{job_id}/retry` → `requeue_job(...)`; return `{"requeued": bool}`.
  - `GET /` → render `dashboard.html` with context {request, counts, last_check,
    channels, jobs (recent ~50)}.
  - `GET /partials/jobs` → render `partials/jobs.html` (htmx fragment: the jobs table
    body) with the recent jobs.

### Tests — `tests/api/test_app.py` (TestClient, `start_background=False`)

`client = TestClient(create_app(config, fake_auth, start_background=False))`.
1. `test_healthz` → 200, `{"status":"ok"}`.
2. `test_status_empty` → 200; counts all zero; scheduler_running False.
3. `test_status_reflects_jobs` — enqueue jobs into `download_path` then GET /api/status
   → counts match.
4. `test_channels_endpoint_lists_saved_channels` — `save_channel_info` a channel →
   GET /api/channels contains its slug.
5. `test_jobs_endpoint_returns_jobs` and `test_jobs_endpoint_filters_by_state`.
6. `test_post_check_invokes_service` — monkeypatch `api.service.check_all_channels`
   (or `api.app.service.check_all_channels`) to return `{"ch-slug": 2}`; POST /api/check
   → 200, body `{"enqueued": {"ch-slug": 2}}`.
7. `test_post_retry_requeues_failed_job` — enqueue+claim+fail a job; POST
   /api/jobs/{id}/retry → `{"requeued": true}`; job back to queued.
8. `test_dashboard_renders_html` — GET / → 200, `text/html`, body contains "Nebula"
   and a known channel/heading.
9. `test_partials_jobs_renders_rows` — enqueue a job; GET /partials/jobs → contains the
   episode slug.

---

## Module 6 — templates (`src/api/templates/`)

- `base.html` — minimal HTML5, `<title>Nebula Archiver</title>`, include htmx via CDN
  `<script src="https://unpkg.com/htmx.org@2"></script>`, a `{% block content %}`.
- `dashboard.html` — extends base. Shows: header "Nebula Archiver"; status cards
  (counts queued/running/done/failed, last_check); a "Check now" button
  `<button hx-post="/api/check" hx-swap="none">Check now</button>`; channels list; a
  jobs table whose `<tbody id="jobs" hx-get="/partials/jobs" hx-trigger="load, every 3s"
  hx-target="#jobs" hx-swap="innerHTML">` auto-refreshes.
- `partials/jobs.html` — just the `<tr>` rows: episode_slug, channel_slug, state, error,
  and a retry button for failed jobs (`hx-post="/api/jobs/{{job.id}}/retry"`).

No unit tests beyond the app-level render tests above (8, 9). Keep markup simple and
valid so `TestClient` gets 200.

---

## Module 7 — `src/serve.py` (entrypoint, smoke only)

```python
def build() -> FastAPI:
    config = Config()
    auth = NebulaUserAuthorization(user_token=config.nebula_api.user_api_token,
                                   authorization_header=config.nebula_api.authorization_header)
    return create_app(config, auth)

def main(host="0.0.0.0", port=8000) -> None:
    import uvicorn
    uvicorn.run(build(), host=host, port=port)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
```

Test — `tests/api/test_serve.py`: 1 test `test_build_creates_app` — monkeypatch
`serve.Config` to return the `config` fixture and `serve.NebulaUserAuthorization` to a
factory returning `fake_auth`, assert `build()` returns a FastAPI instance with routes.
(Do NOT call `main()` / uvicorn.run.)

---

## Order of work (respect dependencies)

1. Module 1 `jobs_db` (+ tests) → green.
2. Module 5a config change (`check_interval_hours`) + `utils/db.list_channel_slugs`
   (+ tests) → green.
3. Module 5 conftest fixtures (`tests/api/conftest.py`, `tests/api/__init__.py`).
4. Module 2 `service` (+ tests) → green.
5. Module 3 `worker` (+ tests) → green.
6. Module 4 `scheduler` (+ tests) → green.
7. Module 5 `app` (+ tests) → green.
8. Module 6 templates (make app render tests pass).
9. Module 7 `serve` (+ test) → green.
10. `pipenv run ruff check src tests` and `pipenv run ruff format src tests` on NEW
    files only (don't touch the 6 pre-existing ruff issues noted in handoff).
11. Full suite: `pipenv run pytest -q` — all prior 120 + new tests pass.

## Definition of done

- `pipenv run pytest -q` green, with the new tests added and the original 120 intact.
- `pipenv run python -c "from api.app import create_app"` imports clean.
- Manual smoke (optional, not in CI): `cd src && pipenv run uvicorn serve:build --factory`
  starts and `/healthz` returns ok. Document but don't automate.
- No network/yt-dlp executed in tests.
