import logging
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from config.config import Config
from models.nebula.episode import NebulaChannelVideoContentEpisodeResult
from models.nebula.fetched import NebulaChannelVideoContentResponseModel
from models.nebula.video_attributes import VideoNebulaAttributes
from nebula_api.authorization import NebulaUserAuthorization
from nebula_api.channel_videos import get_channel_video_content
from nebula_api.streaming import get_streaming_information_by_episode
from nebula_api.video_feed import get_all_channels_slugs_from_video_feed
from utils.db import load_channel_info, save_channel_info
from utils.downloader import download_subtitles, download_thumbnail, download_video
from utils.filtering import filter_out_episodes
from utils.metadata_files_manager import create_nfo_for_channel, create_nfo_for_video


def main(config: Config | None = None, auth: NebulaUserAuthorization | None = None) -> None:
    config = config or Config()
    auth = auth or NebulaUserAuthorization(
        user_token=config.nebula_api.user_api_token,
        authorization_header=config.nebula_api.authorization_header,
    )
    token_refresh_interval = timedelta(
        hours=config.nebula_api.token_refresh_interval_hours or 6
    )
    last_token_fetch_time = datetime.now()

    if config.nebula_filters.channels_to_parse:
        channels = config.nebula_filters.channels_to_parse
        logging.debug("Using channels from config: %s", channels)
    else:
        channels = get_all_channels_slugs_from_video_feed(
            authorization_header=auth.get_authorization_header(full=True),
            category_feed_selector=config.nebula_filters.category_search,
            cursor_times_limit_fetch_maximum=1,
        )
    for channel in channels:
        logging.info("Fetching episodes for channel `%s`", channel)
        channel_data = (
            load_channel_info(channel_slug=channel)
            if config.downloader.load_channel_data_from_db
            else get_channel_video_content(
                channel_slug=channel,
                authorization_header=auth.get_authorization_header(full=True),
            )
        )
        logging.info(
            "Found %s episodes for channel `%s`",
            len(channel_data.episodes.results),
            channel,
        )
        filtered_episodes = list(
            filter_out_episodes(
                filter_settings=config.nebula_filters,
                episodes=channel_data.episodes.results,
            )
        )

        unique_publication_years = {
            datetime.fromisoformat(episode.published_at).year
            for episode in filtered_episodes
        }

        logging.info("Filtered down to %s episodes", len(filtered_episodes))
        channel_directory = save_channel_info(
            channel_slug=channel,
            channel_data=channel_data.details,
            episodes_data=channel_data.episodes,
            output_directory=config.downloader.download_path,
        )

        directory_structure = create_directory_structure_for_channel(
            channel, channel_data, channel_directory, unique_publication_years
        )

        episodes_to_download = remove_downloaded_episodes_from_results(
            filtered_episodes, directory_structure
        )

        for episode in episodes_to_download:
            if (datetime.now() - last_token_fetch_time) > token_refresh_interval:
                auth.refresh_authorization_token()
                last_token_fetch_time = datetime.now()
            download_episode(channel, channel_directory, episode, auth)


def download_episode(
    channel: str,
    channel_directory: Path,
    episode: NebulaChannelVideoContentEpisodeResult,
    auth: NebulaUserAuthorization,
) -> None:
    logging.info("Downloading episode `%s` from channel `%s`", episode.slug, channel)
    publication_year = datetime.fromisoformat(episode.published_at).year
    season_directory_for_channel = (
        "Specials"
        if VideoNebulaAttributes.IS_NEBULA_ORIGINAL in episode.attributes
        else f"Season {publication_year}"
    )

    episode_directory = channel_directory / season_directory_for_channel / episode.slug
    episode_directory.mkdir(parents=True, exist_ok=True)
    download_thumbnail(
        str(episode.images.thumbnail.src),
        episode_directory / f"{episode.slug}-thumb.jpg",
    )
    streaming_information = get_streaming_information_by_episode(
        video_slug=episode.slug,
        authorization_header=auth.get_authorization_header(full=True),
    )

    episode_file_path = episode_directory / f"{episode.slug}"
    if not episode_file_path.exists():
        download_video(
            url=str(streaming_information.manifest),
            output_file=episode_file_path,
        )

    download_subtitles(
        subtitles=streaming_information.subtitles,
        output_directory=episode_directory,
    )
    create_nfo_for_video(episode, episode_directory)


def create_directory_structure_for_channel(
    channel: str,
    channel_data: NebulaChannelVideoContentResponseModel,
    channel_directory: Path,
    unique_publication_years: set[int],
) -> defaultdict:
    channel_structure: defaultdict = defaultdict(Path)
    create_nfo_for_channel(
        channel_data=channel_data.details, channel_directory=channel_directory
    )

    download_thumbnail(
        channel_data.details.images["banner"]["src"],
        channel_directory / "backdrop.jpg",
    )
    download_thumbnail(
        channel_data.details.images["avatar"]["src"],
        channel_directory / "logo.jpg",
    )
    download_thumbnail(
        channel_data.details.images["avatar"]["src"],
        channel_directory / f"{channel}.jpg",
    )

    for year in unique_publication_years:
        season_directory_for_channel = channel_directory / f"Season {year}"
        season_directory_for_channel.mkdir(parents=True, exist_ok=True)
        download_thumbnail(
            channel_data.details.images["avatar"]["src"],
            channel_directory / f"season{year}-poster.jpg",
        )
        channel_structure[year] = season_directory_for_channel

    return channel_structure


def remove_downloaded_episodes_from_results(
    episodes: list[NebulaChannelVideoContentEpisodeResult],
    directory_structure: defaultdict,
) -> list[NebulaChannelVideoContentEpisodeResult]:
    episodes_to_download = []
    for episode in episodes:
        year = datetime.fromisoformat(episode.published_at).year
        path = directory_structure[year]
        path_to_check = path / episode.slug / f"{episode.slug}.nfo"
        if not path_to_check.is_file():
            episodes_to_download.append(episode)
        else:
            logging.info("Skipping episode `%s` as it already exists", episode.slug)
    return episodes_to_download


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    main()
