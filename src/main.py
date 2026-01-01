import logging
from config.Config import Config
from nebula_api.Authorization import NebulaUserAuthorization
from nebula_api.VideoFeedFetcher import get_all_channels_slugs_from_video_feed
from nebula_api.ChannelVideos import get_channel_video_content
from nebula_api.StreamingInformation import get_streaming_information_by_episode
from models.nebula.VideoAttributes import VideoNebulaAttributes
from utils.MetadataFilesManager import (
    create_channel_subdirectory_and_store_metadata_information, create_nfo_for_video, create_nfo_for_channel
)
from utils.Filtering import filter_out_episodes
from utils.Downloader import download_video, download_subtitles, download_thumbnail
from datetime import datetime

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)

CONFIG = Config()

NEBULA_AUTH = NebulaUserAuthorization(
    user_token=CONFIG.NebulaAPI.USER_API_TOKEN,
    authorization_header=CONFIG.NebulaAPI.AUTHORIZATION_HEADER,
)


def main() -> None:
    if CONFIG.NebulaFilters.CHANNELS_TO_PARSE:
        channels = CONFIG.NebulaFilters.CHANNELS_TO_PARSE
        logging.debug("Using channels from config: %s", channels)
    else:
        channels = get_all_channels_slugs_from_video_feed(
            authorization_header=NEBULA_AUTH.get_authorization_header(full=True),
            category_feed_selector=CONFIG.NebulaFilters.CATEGORY_SEARCH,
            cursor_times_limit_fetch_maximum=1,
        )
    for channel in channels:
        logging.info("Fetching episodes for channel `%s`", channel)
        channel_data = get_channel_video_content(
            channel_slug=channel,
            authorization_header=NEBULA_AUTH.get_authorization_header(full=True),
        )
        logging.info(
            "Found %s episodes for channel `%s`",
            len(channel_data.episodes.results),
            channel,
        )
        filtered_episodes = list(
            filter_out_episodes(
                filter_settings=CONFIG.NebulaFilters,
                episodes=channel_data.episodes.results,
            )
        )

        uniquePublicationYears = {datetime.fromisoformat(episode.published_at).year for episode in filtered_episodes}

        logging.info("Filtered down to %s episodes", len(filtered_episodes))
        channelDirectory = create_channel_subdirectory_and_store_metadata_information(
            channel_slug=channel,
            channel_data=channel_data.details,
            episodes_data=channel_data.episodes,
            output_directory=CONFIG.Downloader.DOWNLOAD_PATH,
        )

        create_nfo_for_channel(
            channel_data=channel_data.details,
            channel_directory=channelDirectory
        )

        download_thumbnail(
            channel_data.details.images["banner"]["src"], channelDirectory / "backdrop.jpg"
        )
        download_thumbnail(
            channel_data.details.images["avatar"]["src"], channelDirectory / "logo.jpg"
        )
        download_thumbnail(
            channel_data.details.images["avatar"]["src"], channelDirectory / f"{channel}.jpg"
        )

        for year in uniquePublicationYears:
            season_directory_for_channel = channelDirectory / f"Season {year}"
            season_directory_for_channel.mkdir(parents=True, exist_ok=True)
            download_thumbnail(channel_data.details.images["avatar"]["src"], channelDirectory / f"season{year}-poster.jpg" )

        for episode in filtered_episodes:
            logging.info(
                "Downloading episode `%s` from channel `%s`",
                episode.slug,
                channel,
            )
            publication_year = datetime.fromisoformat(episode.published_at).year
            season_directory_for_channel = (
                "Specials" if VideoNebulaAttributes.IS_NEBULA_ORIGINAL in episode.attributes else
                f"Season {publication_year}"
            )

            episode_directory = channelDirectory / season_directory_for_channel / episode.slug
            episode_directory.mkdir(parents=True, exist_ok=True)
            download_thumbnail(
                str(episode.images.thumbnail.src), episode_directory / f"{episode.slug}-thumb.jpg"
            )
            streaming_information = get_streaming_information_by_episode(
                video_slug=episode.slug,
                authorization_header=NEBULA_AUTH.get_authorization_header(full=True),
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
            create_nfo_for_video(
               episode, episode_directory
            )
    return


if __name__ == "__main__":
    main()
