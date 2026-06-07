import json
from datetime import datetime
from pathlib import Path

from config.config import Config
from main import download_episode
from models.nebula.episode import NebulaChannelVideoContentEpisodeResult
from models.nebula.fetched import NebulaChannelVideoContentResponseModel
from models.nebula.video_attributes import VideoNebulaAttributes
from nebula_api.channel_videos import get_channel_video_content
from nebula_api.video_feed import get_all_channels_slugs_from_video_feed
from nebula_api.authorization import NebulaUserAuthorization
from utils.db import save_channel_info
from utils.filtering import filter_out_episodes
from utils import jobs_db


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
    Resolve channels from config or by fetching from the video feed.
    """
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
