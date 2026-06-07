# TDD Plan — Settings Page: Add / Remove Channels

Author: Opus (plan). Implement: Sonnet. Verify: Sonnet.

## Goal

Add a **Settings** page to the htmx web UI that lets the user manage which channels
get archived, without editing `config.ini` and restarting:

- **Add a channel** by slug → persist a subscription, then immediately check it
  (validate slug + populate channel/episodes/jobs). Check failure is non-fatal.
- **Remove a channel** → drop it from the download list only. **Downloaded data is
  KEPT by default.** A per-row "also remove data" checkbox additionally purges that
  channel's DB rows.

### Product decisions (locked — do not re-litigate)

1. **"Also remove data" deletes DB ROWS ONLY**: the `channels` row (which cascades to
   `episodes`), the channel's `download_jobs` rows, and the `last_check:<slug>`
   `app_state` key. It **never** touches files on disk (videos, `.nfo`, thumbnails,
   subtitles stay). Re-checking the channel later repopulates the DB; the on-disk
   `.nfo` markers still prevent re-downloads.
2. **Add triggers an immediate check.** Store the slug, then run `check_channel` once.
   If the check raises (bad slug, network), the subscription is still stored and the
   error is surfaced — the slug is not rolled back.

## The core architectural change

Today `service.resolve_channels` returns `config.nebula_filters.channels_to_parse`
(read from `config.ini` at startup, not editable at runtime) or, if that is empty,
the auto-discovery video feed. There is **no mutable, persisted "channels I archive"
list**. This plan introduces one: a new **`subscriptions`** table in `nebula.db` that
becomes the runtime source of truth for which channels to check.

**New `resolve_channels` priority (must keep existing resolve tests green):**

1. If the `subscriptions` table has any slugs → return those (sorted).
2. Else if `config.nebula_filters.channels_to_parse` is set → return it (unchanged
   legacy behavior; existing `test_resolve_channels_uses_config_list` still passes
   because a fresh test DB has zero subscriptions).
3. Else → video feed fallback (existing `test_resolve_channels_falls_back_to_feed`
   still passes — zero subscriptions, empty config list).

**Seeding (so config users see their channels in the UI):** at app startup
(`lifespan`, only when `start_background=True`) call a new
`service.seed_subscriptions_from_config(config)` that, *only if the subscriptions
table is empty*, inserts each `config.nebula_filters.channels_to_parse` slug. This is
idempotent and never overwrites a user-managed list. It must NOT run inside
`resolve_channels` (keeps that function pure-ish and keeps unit tests deterministic).

## Hard rules

- **All commands via `pipenv run`.** Bare python fails (missing deps).
- `pytest.ini` sets `pythonpath = src . tests`. Import app modules WITHOUT `src.`
  prefix: `from utils.db import ...`, `from utils import jobs_db`,
  `from api import service`, `from api.app import create_app`.
- Run `pipenv run pytest` from repo root.
- Tests mock HTTP / downloads. **No real network, no real yt-dlp, no real Nebula
  calls in tests.** Build data with the existing factories in
  `tests/api/conftest.py` (`make_episode`, `make_content`, `config`, `fake_auth`)
  and `tests/models/nebula/` payload builders (`_channel_payload`,
  `_episode_payload`).
- TDD per module: write failing test(s) first (red), implement to green, refactor.
  Run that module's test file after each cycle; run the FULL suite at module end.
- Keep ALL existing 204 tests passing. Do NOT break public signatures in
  `utils/db.py`, `utils/jobs_db.py`, `main.py`, `config/`, `api/worker.py`,
  `api/scheduler.py`. `resolve_channels`'s signature is unchanged (its priority
  logic changes — covered by existing + new tests).
- No AI co-author trailer in any commit.
- Do NOT touch the 6 pre-existing ruff F541/F401 issues in old test files.
- `pipenv run ruff check src tests` and `pipenv run ruff format src tests` on NEW /
  TOUCHED source files only at the end.

## Data shapes already available (confirmed)

- `subscriptions` is NEW (this plan).
- `channels(slug PK, details_json)` + `episodes(channel_slug, slug, published_year,
  episode_json)` with `FK ... ON DELETE CASCADE` — deleting a `channels` row removes
  its `episodes` automatically (PRAGMA foreign_keys = ON is set in `db._connect`).
- `download_jobs(... channel_slug, episode_slug ...)` + `app_state(key, value)` live
  in the same `nebula.db`, owned by `utils/jobs_db.py`.
- `list_channels_with_info(dir)` already returns enriched per-channel dicts
  (`slug,title,description,avatar_url,url,website,episode_count,published_at`).
- Episode factory: `make_episode(slug=..., title=..., duration=..., attributes=[...])`.

---

## Module 1 — `src/utils/db.py`: `subscriptions` table + CRUD + data purge

### 1a. Schema

In `_connect`, add (after the `episodes` table, before `conn.commit()`):

```sql
CREATE TABLE IF NOT EXISTS subscriptions (
    slug      TEXT PRIMARY KEY,
    added_at  TEXT
)
```

`added_at` is an ISO timestamp string (use a module-local `_now()` like
`jobs_db._now()` — `from datetime import datetime; datetime.now().isoformat()`).
Do NOT import `Date.now`-style helpers; mirror the existing `db.py` import of
`datetime`.

### 1b. Functions (append; don't alter existing)

```python
def add_subscription(output_directory: Path, slug: str) -> bool:
    """Insert slug into subscriptions. Return True if newly added,
    False if it was already present. Empty/whitespace slug → ValueError."""

def remove_subscription(output_directory: Path, slug: str) -> bool:
    """Delete slug from subscriptions. Return True if a row was removed,
    False if the slug was not subscribed. Does NOT touch channels/episodes."""

def list_subscriptions(output_directory: Path) -> list[str]:
    """Return all subscribed slugs, sorted alphabetically. [] if none."""

def is_subscribed(output_directory: Path, slug: str) -> bool:
    """True if slug is in subscriptions."""

def delete_channel_data(output_directory: Path, slug: str) -> bool:
    """Delete the channels row for slug (episodes cascade). Return True if a
    channels row existed and was deleted, else False. Does NOT touch the
    subscriptions table, download_jobs, app_state, or any files on disk."""
```

Implementation notes:
- `add_subscription`: strip slug; if falsy → `raise ValueError("slug required")`.
  Use `INSERT OR IGNORE`; detect newness via `cursor.rowcount == 1`.
- `remove_subscription`: `DELETE FROM subscriptions WHERE slug = ?`;
  return `cursor.rowcount > 0`.
- `delete_channel_data`: `DELETE FROM channels WHERE slug = ?` (cascade handles
  episodes); return `cursor.rowcount > 0`. Keep `PRAGMA foreign_keys = ON` (already
  in `_connect`) so the cascade fires.

### Tests — append to `tests/utils/test_db.py`

(Mirror the file's existing style: `tmp_path` for the dir, `_channel_payload` /
`_episode_payload` / `NebulaChannelVideoContentEpisodeResult` for building data,
`save_channel_info` to populate channels+episodes.)

1. `test_add_subscription_new_returns_true` — fresh dir, `add_subscription(dir,"a")`
   is `True`; `list_subscriptions(dir) == ["a"]`.
2. `test_add_subscription_duplicate_returns_false` — add "a" twice; second call
   `False`; list still `["a"]`.
3. `test_add_subscription_empty_raises` — `add_subscription(dir, "")` and `"  "`
   raise `ValueError`.
4. `test_list_subscriptions_sorted` — add "z","a","m" → `["a","m","z"]`.
5. `test_list_subscriptions_empty` — fresh dir → `[]`.
6. `test_is_subscribed` — after adding "a", `is_subscribed(dir,"a")` True,
   `is_subscribed(dir,"b")` False.
7. `test_remove_subscription_present_returns_true` — add "a", remove → `True`,
   list `[]`.
8. `test_remove_subscription_absent_returns_false` — remove "ghost" on fresh dir →
   `False`.
9. `test_remove_subscription_keeps_channel_data` — `save_channel_info("a", ...)` with
   2 episodes, `add_subscription(dir,"a")`, then `remove_subscription(dir,"a")`;
   assert `load_channel_info("a", dir)` STILL returns the channel with 2 episodes
   (removal of subscription must not delete data).
10. `test_delete_channel_data_removes_channel_and_episodes` — `save_channel_info`
    a channel with 2 episodes, `delete_channel_data(dir, slug)` → `True`; then
    `load_channel_info(slug, dir)` raises `ChannelNotFoundError`.
11. `test_delete_channel_data_absent_returns_false` — `delete_channel_data` on a
    never-saved slug → `False`.
12. `test_delete_channel_data_keeps_subscription` — save channel + add subscription,
    `delete_channel_data` → subscription slug STILL in `list_subscriptions` (purging
    data is independent of unsubscribing; the caller orchestrates both).

---

## Module 2 — `src/utils/jobs_db.py`: per-channel job cleanup + state delete

### Functions (append)

```python
def delete_jobs_for_channel(output_directory: Path, channel_slug: str) -> int:
    """Delete all download_jobs rows for channel_slug. Return count deleted."""

def delete_state(output_directory: Path, key: str) -> None:
    """Delete a key from app_state. No-op if absent."""
```

Implementation: plain `DELETE ... WHERE`; `delete_jobs_for_channel` returns
`cursor.rowcount`; `delete_state` ignores missing key.

### Tests — append to `tests/utils/test_jobs_db.py`

1. `test_delete_jobs_for_channel_removes_only_that_channel` — enqueue 2 jobs for
   "ch1" and 1 for "ch2"; `delete_jobs_for_channel(dir,"ch1")` returns `2`;
   `list_jobs(dir)` now only has the "ch2" job.
2. `test_delete_jobs_for_channel_none_returns_zero` — fresh dir →
   `delete_jobs_for_channel(dir,"ghost") == 0`.
3. `test_delete_state_removes_key` — `set_state(dir,"last_check:ch","x")`,
   `delete_state(dir,"last_check:ch")`, then `get_state(dir,"last_check:ch") is None`.
4. `test_delete_state_missing_key_noop` — `delete_state(dir,"nope")` does not raise.

---

## Module 3 — `src/api/service.py`: subscription resolve + add/remove/seed

### 3a. `resolve_channels` priority change

```python
def resolve_channels(config, auth, *, feed=get_all_channels_slugs_from_video_feed):
    subs = db.list_subscriptions(config.downloader.download_path)
    if subs:
        return subs
    if config.nebula_filters.channels_to_parse:
        return config.nebula_filters.channels_to_parse
    return feed(...)  # unchanged feed call
```

Add `from utils import db` (the module already imports `from utils.db import
save_channel_info`; either extend that import to include the new functions or add
`from utils import db` and call `db.list_subscriptions(...)`. Prefer
`from utils import db` for the new calls to keep them grouped; leave the existing
`save_channel_info` import as-is to avoid churn).

### 3b. New service functions

```python
def add_channel(config, auth, slug, *, check=check_channel) -> dict:
    """Subscribe to slug, then check it once (validate + populate).
    - slug stripped; empty → ValueError.
    - db.add_subscription(...) (new flag captured).
    - try: enqueued = check(slug, config, auth); error = None
      except Exception as e: enqueued = None; error = str(e)
        (subscription is NOT rolled back — slug stays).
    Return {"slug", "added": bool, "enqueued": int|None, "error": str|None}."""

def remove_channel(config, slug, *, delete_data: bool = False) -> dict:
    """Unsubscribe from slug. Keep data unless delete_data.
    - removed = db.remove_subscription(...).
    - if delete_data:
        db.delete_channel_data(dir, slug)
        jobs_db.delete_jobs_for_channel(dir, slug)
        jobs_db.delete_state(dir, f"last_check:{slug}")
    Return {"slug", "removed": bool, "data_deleted": bool}.
    data_deleted is True only when delete_data was requested (reflects intent;
    fine even if the channel had no rows to delete)."""

def seed_subscriptions_from_config(config) -> int:
    """If subscriptions table is empty AND config.nebula_filters.channels_to_parse
    is set, add each slug. Idempotent: no-op when subscriptions already exist.
    Return count seeded."""
```

`check_channel` already takes `(channel_slug, config, auth, *, fetch=...)` — call it
as `check(slug, config, auth)`. The `check=` injection point lets tests pass a stub
that returns an int or raises, with no network.

### Tests — append to `tests/api/test_service.py`

resolve_channels:
1. `test_resolve_channels_prefers_subscriptions` — `db.add_subscription(dir,"sub-a")`;
   even though `config` has `channels_to_parse = ch-slug`, `resolve_channels` returns
   `["sub-a"]` and the feed stub is NOT called (pass a `feed` that raises if called).
2. (existing `test_resolve_channels_uses_config_list` /
   `test_resolve_channels_falls_back_to_feed` must STILL pass unchanged — verify them,
   they rely on an empty subscriptions table in a fresh `tmp_path` DB.)

add_channel:
3. `test_add_channel_subscribes_and_checks` — stub `check` returns `3`;
   `add_channel(config, fake_auth, "newch", check=stub)` → `added True`,
   `enqueued == 3`, `error is None`; and `db.is_subscribed(dir,"newch")` True.
4. `test_add_channel_check_failure_keeps_subscription` — stub `check` raises
   `RuntimeError("boom")`; result `error == "boom"`, `enqueued is None`,
   `added True`, and the slug IS still subscribed.
5. `test_add_channel_duplicate_added_false` — pre-add "dup"; `add_channel` with stub
   check → `added False` (still re-checked; `enqueued` reflects stub).
6. `test_add_channel_empty_slug_raises` — `add_channel(config, fake_auth, "  ")`
   raises `ValueError`.

remove_channel:
7. `test_remove_channel_keeps_data_by_default` — `save_channel_info` a channel with
   episodes, `db.add_subscription`, enqueue a job for it, `set_state` its last_check.
   `remove_channel(config, slug)` → `removed True`, `data_deleted False`; assert
   `is_subscribed` now False BUT `load_channel_info(slug,dir)` still works, the job
   still in `list_jobs`, and `get_state(last_check:slug)` still set.
8. `test_remove_channel_delete_data_purges` — same setup, `remove_channel(config,
   slug, delete_data=True)` → `removed True`, `data_deleted True`; assert
   `load_channel_info` raises `ChannelNotFoundError`, no jobs for that channel in
   `list_jobs`, `get_state(last_check:slug) is None`, and `is_subscribed` False.
9. `test_remove_channel_absent` — `remove_channel(config,"ghost")` →
   `removed False`, `data_deleted False`, no exception.

seed:
10. `test_seed_subscriptions_from_config_seeds_when_empty` — `config` has
    `channels_to_parse = ch-slug`; `seed_subscriptions_from_config(config)` returns
    `1`, `list_subscriptions(dir) == ["ch-slug"]`.
11. `test_seed_subscriptions_idempotent` — pre-add "existing"; seeding returns `0`
    and does NOT add the config slug (user list wins).

(Build configs without `channels_to_parse` by writing an INI with
`channels_to_parse =` empty, mirroring the existing
`test_resolve_channels_falls_back_to_feed` setup in this file.)

---

## Module 4 — `src/api/app.py`: settings routes

### 4a. Startup seeding

In `lifespan`, inside the `if start_background:` block (before/after worker start is
fine), call `service.seed_subscriptions_from_config(config)`. Import `service` is
already present (`from api import presentation, service`).

### 4b. View helper

```python
def _subscriptions_view() -> list[dict]:
    """Each subscribed slug joined with its channel info (if data exists).
    Returns dicts: {slug, subscribed: True, title, avatar_url, url,
    episode_count, last_check, has_data: bool}."""
    subs = db.list_subscriptions(download_path)
    info_by_slug = {c["slug"]: c for c in list_channels_with_info(download_path)}
    rows = []
    for slug in subs:
        info = info_by_slug.get(slug)
        rows.append({
            "slug": slug,
            "subscribed": True,
            "title": (info or {}).get("title", slug),
            "avatar_url": (info or {}).get("avatar_url"),
            "url": (info or {}).get("url", f"https://nebula.tv/{slug}"),
            "episode_count": (info or {}).get("episode_count", 0),
            "last_check": jobs_db.get_state(download_path, f"last_check:{slug}"),
            "has_data": info is not None,
        })
    return rows
```

Add `from utils import db` at module top (alongside existing `from utils import
jobs_db` and `from utils.db import list_channels_with_info`).

### 4c. Routes

```python
@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    template = env.get_template("settings.html")
    return HTMLResponse(template.render({
        "request": request,
        "subscriptions": _subscriptions_view(),
    }))

@app.post("/api/channels/add", response_class=HTMLResponse)
async def add_channel_route(slug: str = Form(...)):
    service.add_channel(config, auth, slug)
    template = env.get_template("partials/subscriptions.html")
    return HTMLResponse(template.render({"subscriptions": _subscriptions_view()}))

@app.post("/api/channels/remove", response_class=HTMLResponse)
async def remove_channel_route(
    slug: str = Form(...),
    delete_data: bool = Form(False),
):
    service.remove_channel(config, slug, delete_data=delete_data)
    template = env.get_template("partials/subscriptions.html")
    return HTMLResponse(template.render({"subscriptions": _subscriptions_view()}))

@app.get("/partials/subscriptions", response_class=HTMLResponse)
async def partials_subscriptions(request: Request):
    template = env.get_template("partials/subscriptions.html")
    return HTMLResponse(template.render({"subscriptions": _subscriptions_view()}))
```

- Import `Form`: `from fastapi import FastAPI, Query, Form`. (`python-multipart` is
  already a dependency — confirmed in Pipfile from session 4.)
- An unchecked HTML checkbox sends NO field; `delete_data: bool = Form(False)`
  defaults to False. A checked box sends `delete_data=true`/`on` — FastAPI coerces
  `"true"`, `"on"`, `"1"` to `True`. In tests POST `data={"slug": "...",
  "delete_data": "true"}` to exercise the purge path; omit the key for the keep path.
- These return the rendered subscriptions partial so htmx can swap the list in place.

### Tests — append to `tests/api/test_app.py`

(Use `TestClient(create_app(config, fake_auth, start_background=False))` — note
`start_background=False` means seeding does NOT run automatically, so tests control
subscription state directly via `db.add_subscription` / the add route.)

1. `test_settings_page_renders` — GET `/settings` → 200, body contains a recognizable
   marker (e.g. `"Settings"` heading and the add-channel form `action`/`hx-post`
   `"/api/channels/add"`).
2. `test_settings_lists_subscriptions` — `db.add_subscription(download_path,"ch-a")`;
   GET `/settings` → body contains `"ch-a"`.
3. `test_add_channel_route_subscribes` — monkeypatch/patch
   `api.service.check_channel` (or pass through a stub via patching
   `service.add_channel`'s check) so NO network: simplest is
   `mocker.patch("api.service.check_channel", return_value=0)`. POST
   `/api/channels/add` `data={"slug":"new-ch"}` → 200, and
   `db.is_subscribed(download_path,"new-ch")` True; response body lists `"new-ch"`.
4. `test_remove_channel_route_keeps_data` — `save_channel_info` "rm-ch" with episodes,
   `db.add_subscription`; POST `/api/channels/remove` `data={"slug":"rm-ch"}`
   (no delete_data) → 200; `is_subscribed` False but `load_channel_info("rm-ch",...)`
   still returns the channel.
5. `test_remove_channel_route_delete_data_purges` — same setup; POST
   `/api/channels/remove` `data={"slug":"rm-ch","delete_data":"true"}` → 200;
   `load_channel_info` raises `ChannelNotFoundError`.
6. `test_dashboard_has_settings_link` — GET `/` → body contains `href="/settings"`.

Use `pytest-mock`'s `mocker` (already used in the suite) to patch
`api.service.check_channel` for the add route so no real fetch happens. Patch the
name where it's looked up: `api.service.check_channel` (because `add_channel` calls
the module-level `check_channel` via its default arg, patch BEFORE the route
resolves the default — patching `api.service.check_channel` works since the default
is bound at call time only if referenced as `check_channel`; to be safe, have
`add_channel`'s body reference the injected `check` param whose default is the
module global, and patch `api.service.check_channel`). Confirm no network by also
asserting the patched mock was called.

> Implementer note: if patching the default proves fiddly, the cleaner route is to
> patch `api.service.add_channel` itself to a stub that only calls
> `db.add_subscription`, and assert the subscription result. Either is acceptable as
> long as NO real network/yt-dlp runs.

---

## Module 5 — templates

### `partials/subscriptions.html` (new)

Renders the list of subscribed channels with a remove form per row:

```html
<ul class="sub-list" id="sub-list">
  {% for c in subscriptions %}
  <li class="sub-row" data-slug="{{ c.slug }}">
    {% if c.avatar_url %}<img class="avatar" src="{{ c.avatar_url }}" alt="" loading="lazy">{% endif %}
    <div class="sub-meta">
      <div class="channel-title">
        <a href="{{ c.url }}" target="_blank" rel="noopener">{{ c.title or c.slug }}</a>
      </div>
      <div class="channel-sub">
        {{ c.episode_count }} videos
        {% if not c.has_data %}· not yet checked{% endif %}
      </div>
    </div>
    <form class="sub-remove" hx-post="/api/channels/remove" hx-target="#sub-list" hx-swap="outerHTML">
      <input type="hidden" name="slug" value="{{ c.slug }}">
      <label class="del-data">
        <input type="checkbox" name="delete_data" value="true"> also remove data
      </label>
      <button type="submit">Remove</button>
    </form>
  </li>
  {% else %}
  <li class="sub-empty">No channels yet. Add one above.</li>
  {% endfor %}
</ul>
```

### `settings.html` (new)

```html
{% extends "base.html" %}
{% block content %}
<h2>Settings</h2>
<a href="/">&larr; Dashboard</a>

<h3>Add a channel</h3>
<form hx-post="/api/channels/add" hx-target="#sub-list" hx-swap="outerHTML" class="add-form">
  <input type="text" name="slug" placeholder="channel-slug" required>
  <button type="submit">Add</button>
</form>
<p class="hint">Enter the channel slug from its Nebula URL (nebula.tv/<b>slug</b>).</p>

<h3>Archived channels</h3>
{% include "partials/subscriptions.html" %}
{% endblock %}
```

### `dashboard.html` (edit)

Add a Settings link near the "Check now" button, e.g. right after it:

```html
<a href="/settings" class="nav-link">Settings</a>
```

### `base.html` (edit — append CSS only, keep existing)

Add styles for `.sub-list`/`.sub-row` (flex rows, gap, padding, bottom border),
`.sub-meta`, `.sub-remove` (flex, gap, align right via `margin-left:auto`),
`.del-data` (small font), `.add-form` (flex, gap), `.hint` (muted small),
`.nav-link` (button-like link). Reuse existing `.avatar`, `.channel-title`,
`.channel-sub`.

No template-only unit tests beyond Module 4's render assertions. Keep markup valid so
`TestClient` returns 200 and asserted substrings appear.

---

## Order of work

1. Module 1 `utils/db.py` subscriptions + `delete_channel_data` (+ test_db) → green.
2. Module 2 `utils/jobs_db.py` cleanup helpers (+ test_jobs_db) → green.
3. Module 3 `api/service.py` resolve/add/remove/seed (+ test_service) → green;
   re-run the two existing `resolve_channels` tests to confirm unchanged behavior.
4. Module 4 `api/app.py` routes + seeding (+ test_app) → green.
5. Module 5 templates → make Module 4 render assertions pass.
6. `pipenv run ruff check src tests` + `pipenv run ruff format src tests` on
   NEW/TOUCHED source files.
7. Full suite: `pipenv run pytest -q` — all prior 204 + new tests pass.

## Definition of done

- `pipenv run pytest -q` green: original 204 + new db/jobs_db/service/app tests.
- `pipenv run python -c "from api.app import create_app; from api import service;
  from utils import db, jobs_db; db.list_subscriptions; service.add_channel;
  service.remove_channel"` imports clean.
- Removing a channel WITHOUT the checkbox leaves `channels`/`episodes`/
  `download_jobs` rows and `last_check` intact (verified by test 4 of Module 4 and
  test 7 of Module 3).
- Removing WITH the checkbox purges only DB rows; **no file-deletion code exists
  anywhere in this change** (grep the diff for `rmtree`/`unlink`/`os.remove` → none).
- `resolve_channels` prefers subscriptions, falls back to config then feed; existing
  resolve tests still pass.
- No network / yt-dlp executed in tests.
- Manual smoke (optional, not CI): `cd src && pipenv run uvicorn serve:build
  --factory` → `/settings` lists channels, add form populates a channel, remove keeps
  data, remove+checkbox drops it from the list and DB.
