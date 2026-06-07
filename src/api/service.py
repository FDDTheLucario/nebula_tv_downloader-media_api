import json
import logging
from datetime import datetime
from pathlib import Path

from config.config import Config
from main import download_episode
from models.nebula.episode import NebulaChannelVideoContentEpisodeResult
from models.nebula.fetched import NebulaChannelVideoContentResponseModel
from models.nebula.video_attributes import VideoNebulaAttributes
from nebula_api.channel_directory import get_channel_directory
from nebula_api.channel_videos import get_channel_video_content
from nebula_api.video_feed import get_all_channels_slugs_from_video_feed
from nebula_api.authorization import NebulaUserAuthorization
from utils.db import save_channel_info
from utils.filtering import filter_out_episodes
from utils import db, jobs_db


def _now() -> str:
    """Return current timestamp in ISO format."""
    return datetime.now().isoformat()


def episode_nfo_path(
    download_path: Path,
    channel_slug: str,
    episode: NebulaChannelVideoContentEpisodeResult,
) -> Path:
    """
    Determine the path to an episode's NFO file.
    Specials for IS_NEBULA_ORIGINAL, otherwise Season <year>.
    """
    if VideoNebulaAttributes.IS_NEBULA_ORIGINAL in episode.attributes:
        season = "Specials"
    else:
        year = datetime.fromisoformat(episode.published_at).year
        season = f"Season {year}"

    return download_path / channel_slug / season / episode.slug / f"{episode.slug}.nfo"


def find_new_episodes(
    download_path: Path,
    channel_slug: str,
    content: NebulaChannelVideoContentResponseModel,
    filter_settings,
) -> list[NebulaChannelVideoContentEpisodeResult]:
    """
    Filter episodes and keep only those without existing NFO files.
    """
    filtered = filter_out_episodes(filter_settings, content.episodes.results)
    return [
        ep
        for ep in filtered
        if not episode_nfo_path(download_path, channel_slug, ep).exists()
    ]


def check_channel(
    channel_slug: str,
    config: Config,
    auth: NebulaUserAuthorization,
    *,
    fetch=get_channel_video_content,
) -> int:
    """
    Check a channel for new episodes.
    - Fetch channel content
    - Save channel info
    - Find new episodes
    - Enqueue jobs for new episodes
    - Set last_check state
    Return count of newly enqueued jobs.
    """
    content = fetch(
        channel_slug=channel_slug,
        authorization_header=auth.get_authorization_header(full=True),
    )
    save_channel_info(
        channel_slug=channel_slug,
        channel_data=content.details,
        episodes_data=content.episodes,
        output_directory=config.downloader.download_path,
    )
    new_episodes = find_new_episodes(
        config.downloader.download_path,
        channel_slug,
        content,
        config.nebula_filters,
    )

    enqueued_count = 0
    for ep in new_episodes:
        if jobs_db.enqueue_job(
            config.downloader.download_path,
            channel_slug,
            ep.slug,
            ep.model_dump_json(),
        ):
            enqueued_count += 1

    jobs_db.set_state(
        config.downloader.download_path,
        f"last_check:{channel_slug}",
        _now(),
    )

    return enqueued_count


def resolve_channels(
    config: Config,
    auth: NebulaUserAuthorization,
    *,
    feed=get_all_channels_slugs_from_video_feed,
) -> list[str]:
    """
    Resolve channels: subscriptions table first, then config list, then feed.
    """
    subs = db.list_subscriptions(config.downloader.download_path)
    if subs:
        return subs

    if config.nebula_filters.channels_to_parse:
        return config.nebula_filters.channels_to_parse

    return feed(
        authorization_header=auth.get_authorization_header(full=True),
        category_feed_selector=config.nebula_filters.category_search,
        cursor_times_limit_fetch_maximum=1,
    )


def check_all_channels(config: Config, auth: NebulaUserAuthorization) -> dict[str, int]:
    """
    Check all configured channels.
    Return dict mapping channel_slug -> count of newly enqueued jobs.
    """
    channels = resolve_channels(config, auth)
    result = {}
    for ch in channels:
        result[ch] = check_channel(ch, config, auth)

    jobs_db.set_state(
        config.downloader.download_path,
        "last_check",
        _now(),
    )

    return result


def add_channel(
    config: Config,
    auth: NebulaUserAuthorization,
    slug: str,
    *,
    check=check_channel,
) -> dict:
    """Subscribe to slug, then check it once (validate + populate).
    - slug stripped; empty → ValueError.
    - db.add_subscription(...) (new flag captured).
    - try: enqueued = check(slug, config, auth); error = None
      except Exception as e: enqueued = None; error = str(e)
        (subscription is NOT rolled back — slug stays).
    Return {"slug", "added": bool, "enqueued": int|None, "error": str|None}.
    """
    slug = slug.strip()
    if not slug:
        raise ValueError("slug required")
    added = db.add_subscription(config.downloader.download_path, slug)
    try:
        enqueued = check(slug, config, auth)
        error = None
    except Exception as exc:
        enqueued = None
        error = str(exc)
    return {"slug": slug, "added": added, "enqueued": enqueued, "error": error}


def remove_channel(
    config: Config,
    slug: str,
    *,
    delete_data: bool = False,
) -> dict:
    """Unsubscribe from slug. Keep data unless delete_data.
    Return {"slug", "removed": bool, "data_deleted": bool}.
    """
    download_path = config.downloader.download_path
    removed = db.remove_subscription(download_path, slug)
    if delete_data:
        db.delete_channel_data(download_path, slug)
        jobs_db.delete_jobs_for_channel(download_path, slug)
        jobs_db.delete_state(download_path, f"last_check:{slug}")
    return {"slug": slug, "removed": removed, "data_deleted": delete_data}


def seed_subscriptions_from_config(config: Config) -> int:
    """If subscriptions table is empty AND config.nebula_filters.channels_to_parse
    is set, add each slug. Idempotent: no-op when subscriptions already exist.
    Return count seeded.
    """
    download_path = config.downloader.download_path
    if db.list_subscriptions(download_path):
        return 0
    slugs = config.nebula_filters.channels_to_parse or []
    count = 0
    for slug in slugs:
        if db.add_subscription(download_path, slug):
            count += 1
    return count


DIRECTORY_CACHE_KEY = "channel_directory_cache"
DIRECTORY_TTL_SECONDS = 6 * 60 * 60  # 6h


def get_cached_directory(
    config: Config,
    auth: NebulaUserAuthorization,
    *,
    fetch=get_channel_directory,
    now=_now,
    ttl_seconds: int = DIRECTORY_TTL_SECONDS,
    force: bool = False,
) -> list[dict]:
    """Return the channel directory as a list of {slug,title,avatar_url} dicts.
    Served from app_state JSON cache when fresh; otherwise fetched live, cached,
    and returned. On a live-fetch failure, fall back to a stale cache if present;
    if none, return []. Never raises."""
    download_path = config.downloader.download_path
    cached = jobs_db.get_state(download_path, DIRECTORY_CACHE_KEY)
    cached_channels: list[dict] = []
    if cached:
        try:
            payload = json.loads(cached)
            cached_channels = payload.get("channels", [])
            fetched_at = payload.get("fetched_at")
            if not force and fetched_at:
                age = (
                    datetime.fromisoformat(now()) - datetime.fromisoformat(fetched_at)
                ).total_seconds()
                if age < ttl_seconds:
                    return cached_channels
        except (json.JSONDecodeError, ValueError, TypeError):
            cached_channels = []

    try:
        results = fetch(auth.get_authorization_header(full=True))
    except Exception:
        logging.warning("Channel directory fetch failed; serving stale cache")
        return cached_channels

    channels = [
        {"slug": r.slug, "title": r.title, "avatar_url": r.avatar_url()}
        for r in results
    ]
    jobs_db.set_state(
        download_path,
        DIRECTORY_CACHE_KEY,
        json.dumps({"fetched_at": now(), "channels": channels}),
    )
    return channels


def _match_rank(query: str, slug: str, title: str) -> int | None:
    """Rank a candidate against query (lower = better); None if no match."""
    slug_cf = slug.casefold()
    title_cf = title.casefold()
    if slug_cf == query:
        return 0
    if slug_cf.startswith(query):
        return 1
    if title_cf.startswith(query):
        return 2
    if query in slug_cf or query in title_cf:
        return 3
    return None


def search_channels(
    config: Config,
    auth: NebulaUserAuthorization,
    query: str,
    *,
    limit: int = 8,
    directory=get_cached_directory,
) -> list[dict]:
    """Return up to `limit` channel suggestions matching `query`, merged from
    local DB channels (+subscriptions) and the cached Nebula directory.
    Each dict: {slug, title, avatar_url, subscribed: bool, source}.
    Empty/whitespace query → []."""
    q = query.strip().casefold()
    if not q:
        return []

    download_path = config.downloader.download_path

    merged: dict[str, dict] = {}
    for info in db.list_channels_with_info(download_path):
        merged[info["slug"]] = {
            "slug": info["slug"],
            "title": info.get("title") or info["slug"],
            "avatar_url": info.get("avatar_url"),
            "source": "local",
        }
    for slug in db.list_subscriptions(download_path):
        if slug not in merged:
            merged[slug] = {
                "slug": slug,
                "title": slug,
                "avatar_url": None,
                "source": "local",
            }
    for item in directory(config, auth):
        if item["slug"] not in merged:
            merged[item["slug"]] = {
                "slug": item["slug"],
                "title": item.get("title") or item["slug"],
                "avatar_url": item.get("avatar_url"),
                "source": "remote",
            }

    ranked = []
    for entry in merged.values():
        rank = _match_rank(q, entry["slug"], entry["title"])
        if rank is not None:
            ranked.append((rank, entry["slug"], entry))

    ranked.sort(key=lambda t: (t[0], t[1]))

    results = []
    for _, _, entry in ranked[:limit]:
        results.append(
            {
                **entry,
                "subscribed": db.is_subscribed(download_path, entry["slug"]),
            }
        )
    return results


def process_job(
    job: dict,
    config: Config,
    auth: NebulaUserAuthorization,
    *,
    downloader=download_episode,
) -> None:
    """
    Process a single download job.
    - Reconstruct episode from JSON
    - Create channel directory
    - Call downloader
    """
    episode = NebulaChannelVideoContentEpisodeResult(**json.loads(job["episode_json"]))
    channel_dir = config.downloader.download_path / job["channel_slug"]
    channel_dir.mkdir(parents=True, exist_ok=True)
    downloader(job["channel_slug"], channel_dir, episode, auth)
