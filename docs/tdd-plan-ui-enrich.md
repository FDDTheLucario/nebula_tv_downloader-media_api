# TDD Plan — Enrich UI with Channel & Video Info

Author: Opus (plan). Implement: Sonnet. Verify: Sonnet.

## Goal

The htmx dashboard currently shows channels as bare slug tags and jobs as
`episode_slug / channel_slug / state`. Enrich it with the rich data already stored
in `nebula.db`:

- **Channels** → cards with avatar image, title, episode count, per-channel
  last-checked time, description snippet.
- **Jobs/videos** → thumbnail, episode title (not slug), channel title, formatted
  duration, published date, attribute badges (Original / Plus / First).

**No new download/scheduler/queue logic.** This is a presentation layer:
two pure helpers, one DB read helper, route-context decoration, and template +
CSS changes. All source data already exists in the `channels` / `episodes` /
`download_jobs` / `app_state` tables.

## Hard rules

- **All commands via `pipenv run`.** Bare python fails (missing deps).
- `pytest.ini` sets `pythonpath = src . tests`. Import app modules WITHOUT `src.`
  prefix: `from api.presentation import ...`, `from utils.db import ...`,
  `from api.app import create_app`.
- Run `pipenv run pytest` from repo root.
- Tests mock HTTP / downloads. **No real network, no real yt-dlp, no real Nebula
  calls in tests.** Build data with the existing factories in `tests/api/conftest.py`
  (`make_episode`, `make_content`) and `tests/models/nebula/`.
- TDD per module: write test(s) first (red), implement to green, refactor. Run that
  module's test file after each cycle; run the FULL suite at module end.
- Keep ALL existing 178 tests passing. Do not break public signatures in
  `utils/db.py`, `main.py`, `config/`, `api/service.py`, `api/worker.py`,
  `api/scheduler.py`. The ONE existing test that legitimately changes shape is
  `tests/api/test_app.py::test_channels_endpoint_lists_saved_channels` (see Module 3) —
  update it, don't delete it.
- No AI co-author trailer in any commit.
- Do NOT touch the 6 pre-existing ruff F541/F401 issues in old test files.
- `pipenv run ruff check src tests` and `pipenv run ruff format src tests` on NEW
  files only at the end.

## Data available (already in the DB — confirmed against models)

- **Channel** `details_json` (`models/nebula/channel.py`): `slug`, `title`,
  `description`, `published_at`, `assets`/`images` (raw dicts, often `{}` in tests —
  do NOT rely on them for the avatar).
- **Episode** `episode_json` (`models/nebula/episode.py`), present in BOTH the
  `episodes` table AND each `download_jobs.episode_json`: `slug`, `title`,
  `description`, `short_description`, `duration` (int seconds), `published_at`
  (ISO, e.g. `"2024-01-01T00:00:00Z"`), `images.thumbnail.src` (URL string),
  `images.channel_avatar.src` (URL string), `attributes` (list of enum **values**:
  `is_nebula_original`, `is_nebula_plus`, `is_nebula_first`, `free_sample_eligible`),
  `share_url`, `channel_title`.
- **Serialization note:** jobs store `ep.model_dump_json()` → enum attributes are the
  string **values** (`"is_nebula_original"`), and `images.*.src` are plain URL
  strings. The `episodes` table stores `model_dump()` + `default=str`. Both decode to
  the same value strings for our purposes. Avatar/thumbnail come from episode JSON,
  NOT channel JSON.

---

## Module 1 — `src/api/presentation.py` (pure view helpers, no IO)

Pure functions, fully unit-testable. Implement first; everything else consumes them.

```python
import json

_BADGE_LABELS = {
    "is_nebula_original": "Original",
    "is_nebula_plus": "Plus",
    "is_nebula_first": "First",
}


def format_duration(seconds) -> str:
    """Seconds → 'M:SS' or 'H:MM:SS'. None/0/negative → '0:00'."""


def attribute_badges(attributes) -> list[str]:
    """Map attribute value strings → human labels, stable order.
    Unknown values (incl. free_sample_eligible) are skipped. None → []."""


def decorate_job(job: dict) -> dict:
    """Return a shallow copy of job with an added 'episode' key.

    Parse job['episode_json']; on success episode = {
        title, url, thumbnail_url, channel_title, duration, duration_display,
        published_at, published_date, badges, share_url
    }. On missing/invalid JSON or KeyError → episode = None (row still renders
    via episode_slug fallback in the template). Never raises."""
```

Details:
- `format_duration`:
  - `None`, non-int, `<= 0` → `"0:00"`.
  - `< 3600` → `f"{m}:{s:02d}"` (e.g. 120 → `"2:00"`, 5 → `"0:05"`).
  - `>= 3600` → `f"{h}:{m:02d}:{s:02d}"` (e.g. 3661 → `"1:01:01"`).
- `attribute_badges`: iterate the input list, append `_BADGE_LABELS[v]` when present,
  preserving input order, no dupes beyond what input has. `None`/empty → `[]`.
- `decorate_job`:
  - `try: ep = json.loads(job["episode_json"])` inside try/except
    `(KeyError, TypeError, ValueError, json.JSONDecodeError)`.
  - `published_date` = first 10 chars of `published_at` (the `YYYY-MM-DD` date) when it
    looks like an ISO string, else the raw value or `""`.
  - `thumbnail_url` = `ep.get("images", {}).get("thumbnail", {}).get("src")` (None-safe).
  - `url` (the watch link) = `ep.get("share_url") or ep.get("episode_url")`; None if
    neither. `share_url` is the canonical Nebula video URL.
  - `duration_display` = `format_duration(ep.get("duration"))`.
  - `badges` = `attribute_badges(ep.get("attributes"))`.
  - Returned dict must keep ALL original job keys (`id`, `channel_slug`,
    `episode_slug`, `state`, `error`, ...). Use `{**job, "episode": episode}`.

### Tests — `tests/api/test_presentation.py` (new)

format_duration:
1. `test_format_duration_none_is_zero` — `format_duration(None) == "0:00"`.
2. `test_format_duration_zero_and_negative` — `0` and `-5` → `"0:00"`.
3. `test_format_duration_under_minute` — `5` → `"0:05"`.
4. `test_format_duration_minutes` — `120` → `"2:00"`; `605` → `"10:05"`.
5. `test_format_duration_hours` — `3661` → `"1:01:01"`.

attribute_badges:
6. `test_attribute_badges_maps_known` — `["is_nebula_original","is_nebula_plus"]`
   → `["Original","Plus"]`.
7. `test_attribute_badges_skips_unknown` — `["free_sample_eligible","is_nebula_first"]`
   → `["First"]`.
8. `test_attribute_badges_none_empty` — `None` → `[]`; `[]` → `[]`.

decorate_job:
9. `test_decorate_job_parses_episode` — build a job dict whose `episode_json` is
   `make_episode(title="My Vid", duration=125, attributes=["is_nebula_plus"]).model_dump_json()`;
   assert `result["episode"]["title"] == "My Vid"`,
   `duration_display == "2:05"`, `badges == ["Plus"]`,
   `thumbnail_url == "https://example.com/img.jpg"`,
   `url == "https://nebula.tv/ep"` (the `share_url` from `_episode_payload`),
   `published_date == "2024-01-01"`.
10. `test_decorate_job_keeps_original_keys` — original `id`/`state`/`episode_slug`
    preserved.
11. `test_decorate_job_invalid_json_episode_none` — `episode_json="not json"` →
    `result["episode"] is None`, original keys intact, no exception.
12. `test_decorate_job_missing_episode_json_key` — job dict without `episode_json` →
    `episode is None`, no exception.

---

## Module 2 — `src/utils/db.py` add `list_channels_with_info`

Append ONE function (don't alter existing ones). Reads channels + episodes tables.

```python
def list_channels_with_info(output_directory: Path) -> list[dict]:
    """Per saved channel, return a dict:
      {slug, title, description, avatar_url, url, website,
       episode_count, published_at}
    Sorted by title (case-insensitive), then slug. [] if no channels.
    avatar_url: from any one of the channel's episodes
    (images.channel_avatar.src); None if the channel has no episodes.
    url: canonical Nebula channel page f"https://nebula.tv/{slug}".
    website: details_json 'website' (creator's own site) or None."""
```

Implementation notes:
- One `_connect`; `SELECT slug, details_json FROM channels`.
- For each channel: `title`/`description`/`published_at`/`website` from
  `json.loads(details_json)` (use `.get`, tolerate missing; `website` may be absent).
- `url` = `f"https://nebula.tv/{slug}"`.
- `episode_count`: `SELECT COUNT(*) FROM episodes WHERE channel_slug = ?`.
- `avatar_url`: `SELECT episode_json FROM episodes WHERE channel_slug = ? LIMIT 1`;
  if a row, `json.loads(...)["images"]["channel_avatar"]["src"]` (None-safe via
  nested `.get`); else None.
- Sort the resulting list in Python: `key=lambda c: (c["title"].lower(), c["slug"])`.

### Tests — append to `tests/utils/test_db.py`

Use the existing `_channel_payload` import and `_episode_payload` /
`NebulaChannelVideoContentEpisodeResult` (mirror how this file already builds
episodes/channels). `tmp_path` for output dir.

1. `test_list_channels_with_info_empty` — fresh dir → `[]`.
2. `test_list_channels_with_info_returns_details` — `save_channel_info` one channel
   (title "Channel", description "Desc") with 2 episodes → list len 1; entry has
   `slug`, `title == "Channel"`, `episode_count == 2`,
   `avatar_url == "https://example.com/img.jpg"`,
   `url == "https://nebula.tv/<slug>"`.
3. `test_list_channels_with_info_zero_episodes_avatar_none` — channel saved with no
   episodes → `episode_count == 0`, `avatar_url is None`.
4. `test_list_channels_with_info_sorted_by_title` — save channels with titles "Zebra"
   (slug z) and "Apple" (slug a) → result order `["Apple","Zebra"]` by title.

---

## Module 3 — `src/api/app.py` route-context enrichment

No new routes. Enrich the context passed to existing routes/templates.

- Add import: `from api import presentation` and switch channels source to
  `from utils.db import list_channel_slugs, list_channels_with_info`.
- Small local helper inside `create_app` (or module-level) to build enriched channels:
  ```python
  def _channels_view():
      channels = list_channels_with_info(download_path)
      for c in channels:
          c["last_check"] = jobs_db.get_state(
              download_path, f"last_check:{c['slug']}"
          )
      return channels
  ```
- `GET /api/channels` → return `_channels_view()` (now a list of dicts, each with a
  `slug` key — **this changes the JSON shape**; update the existing test, see below).
- `GET /` dashboard → context `channels = _channels_view()`,
  `jobs = [presentation.decorate_job(dict(j)) for j in jobs_db.list_jobs(download_path, limit=50)]`.
- `GET /partials/jobs` → same decorated jobs.

### Tests — `tests/api/test_app.py`

UPDATE existing:
- `test_channels_endpoint_lists_saved_channels` — response is now a list of dicts;
  assert `any(c["slug"] == "test-channel" for c in resp.json())` and that the entry
  carries `title` / `episode_count` keys.

ADD:
- `test_channels_endpoint_includes_last_check` — `save_channel_info` a channel, then
  `jobs_db.set_state(download_path, "last_check:test-channel", "2026-06-07T00:00:00")`;
  GET `/api/channels` → that channel's `last_check` equals the set value.
- `test_dashboard_shows_channel_title_and_count` — save a channel "Channel" with 2
  episodes; GET `/` → body contains `"Channel"`, the episode count, and the channel
  link `https://nebula.tv/<slug>`.
- `test_dashboard_shows_video_title_and_duration` — enqueue a job whose episode has
  `title="My Video"`, `duration=125` (use `jobs_db.enqueue_job(download_path,
  "ch", "ep", make_episode(title="My Video", duration=125).model_dump_json())`);
  GET `/` → body contains `"My Video"` and `"2:05"`.
- `test_partials_jobs_shows_badge_and_thumbnail` — enqueue a job with
  `attributes=["is_nebula_plus"]`; GET `/partials/jobs` → body contains `"Plus"`,
  the thumbnail URL `https://example.com/img.jpg`, and the watch link
  `https://nebula.tv/ep` (the episode `share_url`).

(Keep `test_partials_jobs_renders_rows` passing — episode_slug still rendered as
fallback / data attr.)

---

## Module 4 — templates

### `partials/jobs.html`
Each `<tr>` renders, preferring decorated `job.episode`:
- Thumbnail cell: `{% if job.episode and job.episode.thumbnail_url %}<img class="thumb"
  src="{{ job.episode.thumbnail_url }}" alt="" loading="lazy">{% endif %}`.
- Title cell: the title, linked to the watch URL when present —
  `{% if job.episode and job.episode.url %}<a href="{{ job.episode.url }}"
  target="_blank" rel="noopener">{{ job.episode.title or job.episode_slug }}</a>
  {% else %}{{ (job.episode.title if job.episode else None) or job.episode_slug }}
  {% endif %}`, with badges underneath:
  `{% for b in (job.episode.badges if job.episode else []) %}<span class="badge
  badge-{{ b|lower }}">{{ b }}</span>{% endfor %}`.
- Channel: `{{ job.episode.channel_title if job.episode and job.episode.channel_title
  else job.channel_slug }}`.
- Duration: `{{ job.episode.duration_display if job.episode else "" }}`.
- Published: `{{ job.episode.published_date if job.episode else "" }}`.
- State / Error / Retry: unchanged (retry button for failed).
- Keep `episode_slug` present somewhere (title fallback already does) so the existing
  `test_partials_jobs_renders_rows` slug assertion holds. If the episode has a title
  that differs from the slug, also emit the slug as a `title=`/`data-slug` attr to be
  safe — simplest: add `data-slug="{{ job.episode_slug }}"` on the `<tr>`.

### `dashboard.html`
Replace the bare `.channels` tag loop with a channel-card grid:
```html
<div class="channel-grid">
  {% for c in channels %}
  <div class="channel-card">
    {% if c.avatar_url %}<img class="avatar" src="{{ c.avatar_url }}" alt="" loading="lazy">{% endif %}
    <div class="channel-meta">
      <div class="channel-title"><a href="{{ c.url }}" target="_blank" rel="noopener">{{ c.title or c.slug }}</a></div>
      <div class="channel-sub">{{ c.episode_count }} videos</div>
      <div class="channel-sub">{% if c.last_check %}Checked {{ c.last_check[:16] }}{% else %}Never checked{% endif %}</div>
    </div>
  </div>
  {% endfor %}
</div>
```
Update the Jobs table header to add Thumbnail / Title / Channel / Duration / Published
columns (keep State / Error / Action). The `<tbody id="jobs" hx-get="/partials/jobs"
...>` auto-refresh stays.

### `base.html`
Add CSS for: `.channel-grid` (grid auto-fit minmax ~220px), `.channel-card`
(flex, white card), `.avatar` (40–48px round), `.channel-title`/`.channel-sub`,
`img.thumb` (~120px wide, rounded), `.badge` (small pill) with per-type colors
(`.badge-original`, `.badge-plus`, `.badge-first`). Keep existing styles.

No unit tests beyond Module 3's render assertions. Keep markup valid so `TestClient`
gets 200 and the asserted substrings appear.

---

## Order of work

1. Module 1 `api/presentation.py` (+ `tests/api/test_presentation.py`) → green.
2. Module 2 `utils/db.list_channels_with_info` (+ test_db additions) → green.
3. Module 3 `api/app.py` enrichment (+ update/add test_app tests) → green.
4. Module 4 templates → make Module 3 render assertions pass.
5. `pipenv run ruff check src tests` + `pipenv run ruff format src tests` on NEW files.
6. Full suite: `pipenv run pytest -q` — all prior 178 + new tests pass.

## Definition of done

- `pipenv run pytest -q` green: original 178 (minus the one updated test, still
  passing) + new presentation/db/app tests.
- `pipenv run python -c "from api.app import create_app; from api.presentation import decorate_job"`
  imports clean.
- `decorate_job` never raises on malformed `episode_json` (jobs always render).
- No network/yt-dlp executed in tests.
- Manual smoke (optional, not CI): `cd src && pipenv run uvicorn serve:build
  --factory` → `/` shows channel cards with avatars and job rows with thumbnails,
  titles, durations, badges.
