# TDD Plan — Interactive Channel Search (slug autocomplete)

Author: Opus (plan). Implement: Sonnet. Verify: Sonnet.

## Goal

On the Settings page add-channel form, as the user types into the slug box, show a
live **dropdown of matching channels** (slug + title + avatar). Clicking a suggestion
fills the slug input (and the existing Add flow takes over). Source is **hybrid**:
match against channels we already know locally first, then fall back to the full
Nebula channel directory.

### Product decisions (locked — do not re-litigate)

1. **Hybrid source, local-first.** Build the candidate set from (a) channels already in
   `nebula.db` (`list_channels_with_info`) plus subscribed slugs, then (b) the full
   Nebula channel directory. Merge and dedup by slug; local entries win on collisions
   (they carry richer/owned data). Local-only channels still appear even if absent from
   the live directory.
2. **htmx live dropdown.** The slug `<input>` fires a debounced `hx-get` on `keyup`;
   the server returns a rendered dropdown partial swapped in under the input. Clicking a
   row sets the input value to that slug. No new JS framework — htmx + a 2-line inline
   handler only.
3. **Search is client-side over a cached directory.** Confirmed against the live API:
   Nebula has **no working server-side search** — `?text=` / `?q=` are silently ignored
   on every content endpoint (they return the full unfiltered list). So matching is done
   in our code by substring over slug + title.
4. **Add flow is unchanged.** This plan only adds discovery/autocomplete. Selecting a
   suggestion just populates the existing add form; submitting still calls
   `service.add_channel` (from `tdd-plan-channel-settings.md`). Do not alter add/remove.

## Grounded API facts (verified live, read-only, this session)

- **Channel directory endpoint:** `GET https://content.api.nebula.app/video/channels/`
  - Returns `{"next", "previous", "results": [...]}`. **Offset** pagination — `next` is
    a full URL like `…/video/channels/?offset=20&page_size=20` (mirror the existing
    `video_feed` "follow `next` until null" loop; do NOT build cursor URLs by hand).
  - **379 channels total, ~19 pages of 20** at time of writing. Small enough to fetch
    fully and cache.
  - Each result item: `type` == `"video_channel"`, `slug`, `title`, `description`,
    `share_url`, `website`, and `assets.avatar.{16,32,64,128,256,512}.{original,webp}`.
    Avatar for the dropdown: `assets.avatar["128"]["original"]` (may be missing → None).
- **No server-side filter:** `?text=jetlag` / `?q=jetlag` on `/video/channels/`,
  `/video/`, etc. return the SAME alphabetical full list (verified: `text=zzzznotreal`
  still returns `12tone`, `17pages`, …). `/search/` paths 404. Therefore: fetch all,
  filter locally. Do not pass a query param to Nebula expecting it to filter.

## The architectural change

A new read path: **channel discovery**. New `nebula_api/channel_directory.py` client
paginates the directory into lightweight summary models. `api/service.py` gains
`search_channels(...)` that merges local DB channels with a **TTL-cached** copy of the
directory and ranks substring matches. `api/app.py` gains a `GET /api/channels/search`
route returning a dropdown partial. The directory cache lives in `app_state` (existing
k/v table) as JSON so 19 HTTP requests don't fire on every keystroke.

## Hard rules

- **All commands via `pipenv run`.** Run `pipenv run pytest` from repo root.
- `pytest.ini` sets `pythonpath = src . tests`. Import app modules WITHOUT `src.`:
  `from nebula_api.channel_directory import ...`, `from api import service`,
  `from api.app import create_app`, `from utils import db, jobs_db`.
- Tests mock HTTP with `requests-mock` (nebula_api layer) and `pytest-mock` `mocker`
  (service/app layer). **No real network, no real yt-dlp, no real Nebula calls.**
- New Nebula endpoint follows the existing convention: URL template in `models/urls.py`,
  response model under `models/nebula/`, client fn in `nebula_api/` with the
  status-check-then-validate pattern (mirror `video_feed.py`).
- TDD per module: red (failing test) → green → refactor. Run that module's test file
  each cycle; run the FULL suite at module end.
- **Keep all existing tests green** (244 at last count). Do not change public signatures
  of `service.add_channel` / `remove_channel` / `resolve_channels` / `check_channel`,
  `utils/db`, `utils/jobs_db`, `main.py`, `config/`.
- No AI co-author trailer in commits. Do NOT touch the 6 pre-existing ruff F541/F401
  issues in old test files. Run `pipenv run ruff check/format src tests` on NEW/TOUCHED
  source files only, at the end.
- Inject `now`/`fetch` as keyword params anywhere time or network is used, so tests stay
  deterministic (mirror `check_channel(..., *, fetch=...)`).

## Data shapes already available (confirmed)

- `db.list_channels_with_info(dir) -> list[dict]` keys: `slug, title, description,
  avatar_url, url, website, episode_count, published_at`.
- `db.list_subscriptions(dir) -> list[str]`, `db.is_subscribed(dir, slug) -> bool`.
- `jobs_db.get_state(dir, key) -> str|None`, `jobs_db.set_state(dir, key, value)`.
- `tests/api/conftest.py`: `config`, `fake_auth`, `make_episode`, `make_content`.
  `fake_auth.get_authorization_header(full=True)` → `"Bearer test"`.
- `tests/consts.py` holds shared HTTP fixtures; `requests-mock` test style in
  `tests/nebula_api/test_video_feed.py` (list of responses to model pagination).

---

## Module 1 — `models/urls.py` + `models/nebula/channel_directory.py`

### 1a. URL template (append to `models/urls.py`)

```python
NEBULA_API_CONTENT_VIDEO_CHANNELS_DIRECTORY = url_type_adapter.validate_python(
    "https://content.api.nebula.app/video/channels/"
)
```

(No format placeholders — it's the directory root. Pagination is followed via the
response's `next` URL, exactly like `video_feed`.)

### 1b. Response models (new file `src/models/nebula/channel_directory.py`)

```python
from pydantic import BaseModel, HttpUrl


class NebulaChannelDirectoryResult(BaseModel):
    slug: str
    title: str
    type: str | None = None
    description: str | None = None
    assets: dict | None = None          # avatar lives here; keep loose like channel.py
    share_url: HttpUrl | None = None
    website: HttpUrl | None = None

    def avatar_url(self) -> str | None:
        """Best-effort 128px avatar original URL; None if absent."""
        try:
            return self.assets["avatar"]["128"]["original"]
        except (KeyError, TypeError):
            return None


class NebulaChannelDirectoryResponse(BaseModel):
    next: HttpUrl | None = None
    previous: HttpUrl | None = None
    results: list[NebulaChannelDirectoryResult]
```

Keep `assets` as a loose `dict | None` (the real payload is huge and nested — mirror how
`channel.py` keeps `images`/`assets` loose). Only `slug` and `title` are required;
everything else optional so a thin/partial item never blows up validation.

### Tests — new `tests/models/nebula/test_channel_directory.py`

Add a payload builder `_directory_payload(*results)` and
`_directory_result_payload(slug="12tone", title="12tone", with_avatar=True)`.

1. `test_directory_result_parses_minimal` — `{"slug":"x","title":"X"}` validates;
   `avatar_url()` is `None`.
2. `test_directory_result_avatar_url` — full assets payload → `avatar_url()` returns the
   `assets.avatar["128"]["original"]` string.
3. `test_directory_result_avatar_url_missing_keys` — `assets={}` and `assets=None` both
   → `avatar_url()` returns `None` (no exception).
4. `test_directory_response_parses` — `{"next": None, "previous": None, "results":[...]}`
   validates; `len(results) == n`.
5. `test_directory_response_next_url` — `next` set to a valid URL parses as `HttpUrl`.

---

## Module 2 — `nebula_api/channel_directory.py` (paginating client)

```python
def get_channel_directory(
    authorization_header: str,
    max_pages: int = 50,
) -> list[NebulaChannelDirectoryResult]:
    """Walk the full Nebula channel directory, following `next` until exhausted
    or max_pages reached. Returns all channel summary results (unsorted)."""
```

Implementation (mirror `video_feed.get_all_channels_slugs_from_video_feed`):
- GET `unquote(str(NEBULA_API_CONTENT_VIDEO_CHANNELS_DIRECTORY))` with
  `{"Authorization": authorization_header}`.
- On non-200 → `raise Exception(f"Failed to get channel directory: ... {status}")`
  (match the existing message shape so logging/tests are consistent).
- Validate into `NebulaChannelDirectoryResponse`; collect `results`.
- While `data.next is not None and pages < max_pages`: GET `str(data.next)`, validate,
  `extend` results, advance `data.next`, `pages += 1`. (Same non-200 → raise inside the
  loop as `video_feed` does.)
- `max_pages` is a safety cap (directory is ~19 pages; default 50 leaves headroom). When
  the cap is hit with `next` still set, `logging.info` that the directory was truncated
  (no silent cap — see CLAUDE.md "no silent caps" lesson).
- Log total channels found.

### Tests — new `tests/nebula_api/test_channel_directory.py` (requests-mock)

Add directory page fixtures to `tests/consts.py`:
`DIRECTORY_URL = "https://content.api.nebula.app/video/channels/"`, a page-1 JSON with
`next` pointing to page 2 and 2–3 results, and a page-2 JSON with `next: null`.

1. `test_get_channel_directory_single_page` — one page, `next: null` → returns its
   results; `requests_mock.call_count == 1`.
2. `test_get_channel_directory_follows_next` — page1(next→page2) then page2(next null);
   result list is the concatenation; `call_count == 2`. (Register the `next` URL as a
   second mocked GET, like `test_video_feed` registers sequential responses.)
3. `test_get_channel_directory_respects_max_pages` — every page has a non-null `next`;
   call with `max_pages=2`; assert exactly 2 requests made and results from 2 pages only
   (cap honored, no infinite loop).
4. `test_get_channel_directory_non_200_raises` — first GET returns 500 → `Exception`
   raised, message contains the status code.
5. `test_get_channel_directory_non_200_mid_pagination_raises` — page1 OK (next set),
   page2 returns 503 → raises.

---

## Module 3 — `api/service.py`: directory cache (TTL)

A small cache so keystrokes don't trigger 19 HTTP requests. Store the directory as JSON
in `app_state` with a fetched-at timestamp; refresh when stale.

```python
DIRECTORY_CACHE_KEY = "channel_directory_cache"
DIRECTORY_TTL_SECONDS = 6 * 60 * 60  # 6h


def get_cached_directory(
    config, auth, *,
    fetch=get_channel_directory,
    now=_now,
    ttl_seconds: int = DIRECTORY_TTL_SECONDS,
    force: bool = False,
) -> list[dict]:
    """Return the channel directory as a list of {slug,title,avatar_url} dicts.
    Served from app_state JSON cache when fresh; otherwise fetched live, cached,
    and returned. On a live-fetch failure, fall back to a stale cache if present;
    if none, return []. Never raises."""
```

Behavior:
- Read `jobs_db.get_state(dir, DIRECTORY_CACHE_KEY)`. If present, JSON-decode to
  `{"fetched_at": iso, "channels": [...]}`.
- Fresh if not `force` and `now()` − `fetched_at` < `ttl_seconds`
  (`datetime.fromisoformat` diff in seconds). Fresh → return cached `channels`.
- Stale/missing/`force` → `fetch(auth.get_authorization_header(full=True))`, map each
  `NebulaChannelDirectoryResult` to `{"slug","title","avatar_url"}` (call `.avatar_url()`),
  `set_state` the JSON with `fetched_at=now()`, return the list.
- If `fetch` raises → log, return the stale cached `channels` if any, else `[]`. (Search
  must degrade gracefully — a directory outage still shows local matches.)
- `now` is the injectable `_now` (already in service); tests pass a stub returning a
  fixed ISO string. `fetch` injectable for no-network tests.

### Tests — append to `tests/api/test_service.py`

1. `test_get_cached_directory_fetches_when_empty` — stub `fetch` returns 2 results;
   `get_cached_directory(config, fake_auth, fetch=stub, now=lambda:"2026-06-07T00:00:00")`
   → 2 dicts with `slug/title/avatar_url`; and `jobs_db.get_state(dir, KEY)` now holds
   JSON with those channels. Assert stub called once.
2. `test_get_cached_directory_serves_fresh_cache` — pre-`set_state` a cache with
   `fetched_at` = `now` minus 1 minute (use the same `now` stub); a `fetch` that RAISES
   if called. Call → returns cached channels, `fetch` NOT called.
3. `test_get_cached_directory_refetches_when_stale` — pre-set cache `fetched_at` 7h
   before `now`; stub `fetch` returns a NEW set; assert fetch called and new set returned
   + persisted.
4. `test_get_cached_directory_force_refetches` — fresh cache present but `force=True` →
   fetch called.
5. `test_get_cached_directory_fetch_error_returns_stale` — stale cache present, `fetch`
   raises → returns the stale channels (no exception).
6. `test_get_cached_directory_fetch_error_no_cache_returns_empty` — no cache, `fetch`
   raises → returns `[]` (no exception).

---

## Module 4 — `api/service.py`: `search_channels` (hybrid + ranking)

```python
def search_channels(
    config, auth, query, *,
    limit: int = 8,
    directory=get_cached_directory,
) -> list[dict]:
    """Return up to `limit` channel suggestions matching `query`, merged from
    local DB channels (+subscriptions) and the cached Nebula directory.
    Each dict: {slug, title, avatar_url, subscribed: bool, source: 'local'|'remote'}.
    Empty/whitespace query → []."""
```

Behavior:
- `q = query.strip().casefold()`; if not `q` → return `[]`.
- **Local set:** `db.list_channels_with_info(dir)` → dicts; also fold in subscribed
  slugs from `db.list_subscriptions(dir)` that aren't already present (title falls back
  to slug, avatar None). Mark each `source="local"`.
- **Remote set:** `directory(config, auth)` (the cached fn; injectable) →
  `source="remote"`.
- **Merge & dedup by slug**, local wins (skip a remote item whose slug is already in
  local). Single combined list.
- **Match:** keep items where `q` is a substring of `slug.casefold()` OR
  `title.casefold()`.
- **Rank** (stable sort, best first):
  1. exact slug match (`slug.casefold() == q`)
  2. slug startswith `q`
  3. title startswith `q`
  4. substring elsewhere
  Tie-break alphabetically by slug. Truncate to `limit`.
- Set `subscribed = db.is_subscribed(dir, slug)` on each returned row (so the dropdown
  can show "✓ added").
- Never raises (directory already degrades to `[]`; local is local).

Note: `search_channels` does NOT call Nebula directly — it goes through
`get_cached_directory`, so a flurry of keystrokes hits the cache, not the network.

### Tests — append to `tests/api/test_service.py`

Helper: a `directory` stub returning a fixed list of
`{"slug","title","avatar_url"}` dicts (no network).

1. `test_search_channels_empty_query_returns_empty` — `""` and `"   "` → `[]`;
   the directory stub is NOT called for the empty case (guard before any work).
2. `test_search_channels_matches_slug_substring` — directory has `jetlag`,
   `jet-lag-the-game`, `legaleagle`; query `"jet"` → returns the two jet* slugs, not
   legaleagle.
3. `test_search_channels_matches_title_substring` — directory item
   `{"slug":"tlg","title":"Jet Lag: The Game"}`; query `"lag"` → matched via title.
4. `test_search_channels_ranking_exact_then_prefix` — directory `jet`, `jetlag`,
   `superjet`; query `"jet"` → order is `jet` (exact), `jetlag` (prefix), `superjet`
   (substring).
5. `test_search_channels_respects_limit` — directory of 20 `jet*` slugs, `limit=5` →
   exactly 5 results.
6. `test_search_channels_local_first_and_marks_subscribed` —
   `save_channel_info` a local channel `jetlag` with a title; `db.add_subscription(dir,
   "jetlag")`; directory stub ALSO returns a `jetlag` (different title). Query `"jet"` →
   exactly one `jetlag` row, `source=="local"`, local title wins, `subscribed is True`.
7. `test_search_channels_includes_remote_only` — query matches a directory-only slug not
   in the DB → row present with `source=="remote"`, `subscribed is False`.
8. `test_search_channels_case_insensitive` — query `"JET"` matches `jetlag`.
9. `test_search_channels_directory_failure_still_returns_local` — `directory` stub
   returns `[]` (simulating outage); a local `jetlag` exists → still returned.

---

## Module 5 — `api/app.py`: search route

```python
@app.get("/api/channels/search", response_class=HTMLResponse)
async def search_channels_route(request: Request, q: str = Query("")):
    results = service.search_channels(config, auth, q)
    template = env.get_template("partials/channel_search.html")
    return HTMLResponse(template.render({"request": request, "results": results, "q": q}))
```

- `Query` is already imported in `app.py` (used elsewhere); confirm and reuse.
- Empty `q` → `service.search_channels` returns `[]` → partial renders nothing (empty
  dropdown). No 422; default `q=""`.
- Returns the dropdown partial only (htmx swaps it under the input).

### Tests — append to `tests/api/test_app.py`

Use `TestClient(create_app(config, fake_auth, start_background=False))` and
`mocker.patch("api.app.service.search_channels", return_value=[...])` to avoid network
(patch at the lookup site `api.app.service.search_channels` — per the handoff lesson:
patching `api.service.check_channel` was ineffective because a default kwarg bound the
name at import; here the route calls `service.search_channels(...)` at request time, so
patching `api.app.service.search_channels` works — assert the mock was called).

1. `test_search_route_returns_matches` — patch `search_channels` → returns 2 dicts; GET
   `/api/channels/search?q=jet` → 200, body contains both slugs; mock called with `"jet"`.
2. `test_search_route_empty_query` — GET `/api/channels/search` (no `q`) → 200, body has
   no result rows (empty dropdown); patched `search_channels` returns `[]`.
3. `test_search_route_subscribed_marker` — one result `subscribed=True` → body shows the
   "added"/✓ marker for it (assert the marker substring).
4. `test_search_route_no_network` — do NOT patch `search_channels`; instead patch
   `api.app.service.get_cached_directory` (or `get_channel_directory`) to return `[]` and
   assert GET succeeds (200) — proves the route path makes no live HTTP when the
   directory layer is stubbed.

---

## Module 6 — templates + wiring

### `partials/channel_search.html` (new)

```html
{% if results %}
<ul class="search-dropdown" id="channel-search-results">
  {% for r in results %}
  <li class="search-row"
      data-slug="{{ r.slug }}"
      onclick="document.getElementById('slug-input').value='{{ r.slug }}';
               document.getElementById('channel-search-results').innerHTML='';">
    {% if r.avatar_url %}<img class="avatar" src="{{ r.avatar_url }}" alt="" loading="lazy">{% endif %}
    <span class="search-title">{{ r.title or r.slug }}</span>
    <span class="search-slug">{{ r.slug }}</span>
    {% if r.subscribed %}<span class="search-added">✓ added</span>{% endif %}
  </li>
  {% endfor %}
</ul>
{% else %}
<ul class="search-dropdown" id="channel-search-results"></ul>
{% endif %}
```

(Empty branch still renders the container element with the stable id so htmx
`outerHTML` swaps stay anchored and the inline `innerHTML=''` clear target exists.)

### `settings.html` (edit the add-form input — from `tdd-plan-channel-settings.md`)

Wire the existing slug input for live search; keep the existing Add button/flow.

```html
<form hx-post="/api/channels/add" hx-target="#sub-list" hx-swap="outerHTML" class="add-form">
  <div class="search-wrap">
    <input type="text" id="slug-input" name="slug" placeholder="search or type a channel slug"
           autocomplete="off" required
           hx-get="/api/channels/search"
           hx-trigger="keyup changed delay:250ms"
           hx-target="#channel-search-results"
           hx-swap="outerHTML"
           name="q">
    <ul class="search-dropdown" id="channel-search-results"></ul>
  </div>
  <button type="submit">Add</button>
</form>
```

> **Implementer gotcha:** htmx sends the input's `name` as the query param. The input
> needs to submit as `slug` to the Add POST but as `q` to the search GET — one element
> can't have two `name`s. Resolve by giving the input `name="slug"` and adding
> `hx-params="*"` is not enough. Cleanest: keep `name="slug"` and set the search request
> param explicitly with `hx-vals='js:{q: event.target.value}'` on the input (drop the
> second `name`). Then the search route reads `q` from `hx-vals` while the form still
> posts `slug`. Verify in the Module 5 test that `?` carries `q`. Pick ONE mechanism and
> cover it with the route test (test 1 already asserts the mock is called with the typed
> value).

### `base.html` (append CSS only)

Styles for `.search-wrap` (position: relative), `.search-dropdown` (absolute, full
width, bordered, max-height + scroll, hidden when empty via `:empty { display:none }`),
`.search-row` (flex, gap, cursor:pointer, hover bg), `.search-title`/`.search-slug`
(muted, smaller), `.search-added` (small, success color), reuse existing `.avatar`.

No template-only unit tests beyond Module 5's render assertions. Keep markup valid so
`TestClient` returns 200 and asserted substrings appear.

---

## Order of work

1. Module 1 — URL + directory models (+ test_channel_directory model tests) → green.
2. Module 2 — `nebula_api/channel_directory.py` client (+ requests-mock tests) → green.
3. Module 3 — `service.get_cached_directory` TTL cache (+ tests) → green.
4. Module 4 — `service.search_channels` hybrid+ranking (+ tests) → green.
5. Module 5 — `app.py` search route (+ tests) → green.
6. Module 6 — templates + wiring → make Module 5 render assertions pass; manual smoke.
7. `pipenv run ruff check src tests` + `pipenv run ruff format src tests` on
   NEW/TOUCHED source only.
8. Full suite: `pipenv run pytest -q` — all prior tests + new ones pass.

## Definition of done

- `pipenv run pytest -q` green: all prior 244 + new model/client/service/app tests.
- `pipenv run python -c "from api.app import create_app; from api import service;
  service.search_channels; service.get_cached_directory;
  from nebula_api.channel_directory import get_channel_directory"` imports clean.
- Typing in the slug box shows a dropdown of matching channels; clicking one fills the
  slug input; submitting Adds via the unchanged flow.
- **No live HTTP per keystroke:** repeated searches hit the `app_state` TTL cache; the
  directory is fetched at most once per `DIRECTORY_TTL_SECONDS`. Verified by Module 3
  test 2 (`fetch` raises if called when cache is fresh).
- Search degrades gracefully: directory outage still returns local matches; empty query
  returns nothing; nothing raises out of `search_channels`.
- No server-side-search assumption baked in (we fetch the full directory and filter
  locally — Nebula's `?text`/`?q` are no-ops, confirmed).
- No file deletion, no yt-dlp, no real network in tests.
- Manual smoke (optional): `cd src && pipenv run uvicorn serve:build --factory` →
  `/settings`, type `jet` → dropdown shows jet* channels with avatars; click fills slug;
  Add works.
