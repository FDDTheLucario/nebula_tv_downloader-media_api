# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CLI tool that archives **all** videos from [Nebula.tv](https://nebula.tv) channels into a
Jellyfin/Kodi-style media library (per-channel directories, `Season <year>` folders, `.nfo`
metadata, thumbnails, subtitles). Requires a paid Nebula subscription and API token. See
`README.md` for token extraction and ToS warnings.

## Commands

Dependencies are managed with **Pipenv** (`Pipfile`, `python_version = 3.14`). `requirements.txt`
is stale/pinned-old — prefer Pipenv.

```bash
pipenv install                       # install deps into virtualenv
pipenv run pytest                    # run all tests
pipenv run pytest tests/utils/test_db.py            # single file
pipenv run pytest tests/utils/test_db.py::test_name # single test
pipenv run coverage run -m pytest && pipenv run coverage report  # coverage
pipenv run ruff check src tests      # lint
pipenv run ruff format src tests     # format
cd src && pipenv run python main.py  # run the archiver (reads config/config.ini)
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

**Per-channel flow in `main()`:** resolve channels (config allow-list or
`get_all_channels_slugs_from_video_feed`) → fetch episodes (live API, or from local DB when
`load_channel_data_from_db`) → `filter_out_episodes` → persist via `save_channel_info` →
`create_directory_structure_for_channel` (channel/season dirs, banner/avatar/poster art, channel
`.nfo`) → `remove_downloaded_episodes_from_results` (skip if `<slug>.nfo` already exists — the
`.nfo` is the "downloaded" marker) → `download_episode` per remaining episode (thumbnail →
streaming manifest via yt-dlp → subtitles → video `.nfo`).

**Output layout:** `<download_path>/<channel_slug>/<Season YYYY | Specials>/<episode_slug>/` —
Nebula Originals go to `Specials`, everything else to `Season <publication_year>`. Channel +
episode metadata lives in `<download_path>/nebula.db` (SQLite), not per-channel JSON files.

## Conventions

- Tests mock HTTP with `requests-mock` / `pytest-mock`; `tests/consts.py` holds shared fixtures.
  Test tree mirrors `src/` (`tests/nebula_api/`, `tests/utils/`, `tests/models/nebula/`).
- New Nebula endpoints: add the URL template to `models/urls.py`, a response model under
  `models/nebula/`, and a client function in `nebula_api/` following the existing
  status-check-then-validate pattern.
- CI (`.gitlab-ci.yml`) runs GitLab SAST/secret-detection only — no test job; DeepSource
  (`.deepsource.toml`) runs Python + coverage + secrets analysis. `# skipcq:` comments suppress
  DeepSource findings.
