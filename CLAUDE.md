# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CLI tool that archives **all** videos from [Nebula.tv](https://nebula.tv) channels into a
Jellyfin/Kodi-style media library (per-channel directories, `Season <year>` folders, `.nfo`
metadata, thumbnails, subtitles). Requires a paid Nebula subscription and API token. See
`README.md` for token extraction and ToS warnings.

## Commands

Dependencies are managed with **Pipenv** (`Pipfile`, `python_version = 3.14`). Pipenv is the only
supported workflow — there is no `requirements.txt`.

```bash
pipenv install                       # install deps into virtualenv
pipenv run pytest                    # run all tests
pipenv run pytest tests/utils/test_db.py            # single file
pipenv run pytest tests/utils/test_db.py::test_name # single test
pipenv run coverage run -m pytest && pipenv run coverage report  # coverage
pipenv run ruff check src tests      # lint
pipenv run ruff format src tests     # format
cd src && pipenv run python main.py  # run the archiver once (CLI / cron style)
cd src && pipenv run python serve.py # run the web UI + background worker/scheduler (uvicorn)
```

`pytest.ini` sets `pythonpath = src . tests`, so tests import app modules as `from config...`,
`from nebula_api...`, etc. (no `src.` prefix). Run pytest from the repo root; run `main.py`
from inside `src/` (config path defaults to relative `config/config.ini`).

## Configuration

`main()` is driven entirely by `src/config/config.ini` (gitignored; copy from
`config.example.ini`). Only `user_api_token` is required. `Config` (`src/config/config.py`) parses
the INI into validated Pydantic models (`src/models/configuration.py`) and exposes
`nebula_api` / `nebula_filters` / `downloader` property groups. `QuotedConfigParser` strips
surrounding quotes; the string `"false"` is the disabled sentinel for `category_search`, and an
empty `channels_to_parse` disables the channel allow-list.

The **web layer** (`serve.py`) does not read the INI at runtime: config lives in a single global
SQLite DB and is edited via the UI. The INI is a one-time migration seed only. The DB location is
the one bootstrap setting that can't live in the DB — resolved by `src/utils/paths.py` in priority
order: `NEBULA_DB_PATH` env → pointer file `~/.config/nebula_archiver/db_path` → XDG default
`~/.local/share/nebula_archiver/nebula.db`. The DB normally lives at `<download_path>/nebula.db`.

## Deployment

`Dockerfile` (repo root) containerizes the web service for 24/7 running: `python:3.14-slim` +
`ffmpeg` (yt-dlp merges `bestvideo+bestaudio`) + `curl` (healthcheck), deps via
`pipenv install --system --deploy`, `CMD ["python", "serve.py"]` from `/app/src`. `serve.py`'s
`main()` binds `0.0.0.0:$PORT` (`PORT` env, default 8000) — set `PORT` to avoid a clash when the
container shares another container's network namespace. Mount a host dir for the media library +
DB and point `NEBULA_DB_PATH` at the DB inside it; `download_path` (stored in the DB config) must
be the container-side path, not a host path. `GET /healthz` is the container healthcheck endpoint.

## Architecture

Layered, dependency-injected pipeline. `main()` in `src/main.py` is the orchestrator; everything
else is a pure-ish helper that takes explicit args (config, auth, paths) — `main(config, auth)`
accepts injected instances, which is how tests drive it.

**Layers (import direction is top → down):**

- `nebula_api/` — thin HTTP clients, one module per Nebula endpoint
  (`authorization`, `channel_videos`, `video_feed`, `streaming`). Each function takes an
  `authorization_header` string, calls `requests`, and returns a validated Pydantic model.
  `channel_videos.get_channel_video_content` walks the cursor pagination until exhausted and
  backs off on HTTP 429 (`TOO_MANY_REQUESTS`) with doubling sleep.
- `models/` — all data shapes. `models/urls.py` holds every Nebula URL as a validated
  `HttpUrl` template (`.format(CHANNEL_SLUG=...)`). `models/configuration.py` = config schema.
  `models/nebula/` = API response schemas; `video_attributes.VideoNebulaAttributes` is the enum
  (`IS_NEBULA_ORIGINAL`, `IS_NEBULA_PLUS`, `IS_NEBULA_FIRST`, `FREE_SAMPLE_ELIGIBLE`) that drives
  filtering and the Specials-vs-Season directory choice.
- `utils/` — side-effecting helpers: `downloader` (yt-dlp video + `requests` thumbnails/subs),
  `filtering` (apply attribute filters to episode lists), `db` (persist/reload channel +
  episode metadata in a single SQLite DB at `<download_path>/nebula.db`; `save_channel_info`
  upserts and replaces a channel's episode set in one transaction and still returns the
  per-channel media dir; `load_channel_info` raises `ChannelNotFoundError` for unknown slugs),
  `metadata_files_manager` (write `.nfo` XML via `dicttoxml`).

**Auth lifecycle:** `NebulaUserAuthorization` exchanges the long-lived `user_api_token` for a
short-lived bearer token at construction. `main()` refreshes it mid-run every
`token_refresh_interval_hours` (default 6) during the download loop. Pass `full=True` to
`get_authorization_header()` to get the `Bearer <token>` form the content API expects.

**Per-channel flow in `main()`** (one channel per iteration):

1. Resolve channels from the config allow-list, else `get_all_channels_slugs_from_video_feed`.
2. Fetch episodes from the live API, or from the local DB when `load_channel_data_from_db`.
3. `filter_out_episodes` to apply the attribute filters.
4. `save_channel_info` to persist channel + episode set in one transaction.
5. `create_directory_structure_for_channel` to make channel/season dirs, art, and channel `.nfo`.
6. `remove_downloaded_episodes_from_results` to skip episodes whose `<slug>.nfo` already exists.
7. `download_episode` per remaining episode: thumbnail → yt-dlp streaming manifest → subtitles → video `.nfo`.

The per-episode `<slug>.nfo` is the "downloaded" marker (step 6) — no `.nfo`, it re-downloads.

**Output layout:** `<download_path>/<channel_slug>/<season-dir>/<episode_slug>/`. Channel + episode
metadata lives in `<download_path>/nebula.db` (SQLite), not per-channel JSON files. Season dir:

| Season dir | When (`main.py:99`) |
|---|---|
| `Specials` | `IS_NEBULA_ORIGINAL` in `episode.attributes` |
| `Season <YYYY>` | otherwise; `<YYYY>` = year of `episode.published_at` |

## Conventions

- Tests mock HTTP with `requests-mock` / `pytest-mock`; `tests/consts.py` holds shared fixtures.
  Test tree mirrors `src/` (`tests/nebula_api/`, `tests/utils/`, `tests/models/nebula/`).
- New Nebula endpoints: add the URL template to `models/urls.py`, a response model under
  `models/nebula/`, and a client function in `nebula_api/` following the existing
  status-check-then-validate pattern.
- CI (`.gitlab-ci.yml`) runs GitLab SAST/secret-detection only — no test job; DeepSource
  (`.deepsource.toml`) runs Python + coverage + secrets analysis. `# skipcq:` comments suppress
  DeepSource findings.
