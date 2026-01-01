from datetime import datetime
import json
from pathlib import Path
from xml.dom.minidom import parseString
from xml.etree.ElementTree import indent

import dicttoxml

from models.nebula.Channel import NebulaChannelVideoContentDetails
from models.nebula.Episode import NebulaChannelVideoContentEpisodeResult
from models.nebula.Fetched import NebulaChannelVideoContentEpisodes


def create_channel_subdirectory_and_store_metadata_information(
    channel_slug: str,
    channel_data: NebulaChannelVideoContentDetails,
    episodes_data: NebulaChannelVideoContentEpisodes,
    output_directory: Path,
) -> Path:
    channel_directory = output_directory / channel_slug
    channel_directory.mkdir(parents=True, exist_ok=True)
    with open(channel_directory / "channel.json", "w") as file:
        json.dump(channel_data.model_dump(), file, indent=4, default=str)
    with open(channel_directory / "episodes.json", "w") as file:
        json.dump(episodes_data.model_dump()["results"], file, indent=4, default=str)
    return channel_directory


def create_nfo_for_video(episode: NebulaChannelVideoContentEpisodeResult, episodeDirectory: Path) -> Path:
    video_nfo_file_path = episodeDirectory / f"{episode.slug}.nfo"
    episode_date = datetime.fromisoformat(episode.published_at)
    print(video_nfo_file_path)
    with open(video_nfo_file_path, "w") as file:
        episode_details_dict = {
            "title": episode.title,
            "showtitle": episode.channel_title,
            "plot": episode.description,
            "unique_id": episode.id,
            "premiered": episode_date.strftime("%Y-%m-%d"),
            "season": episode_date.year
        }
        file.write(parseString(dicttoxml.dicttoxml(episode_details_dict, attr_type=False, custom_root="episodedetails")).toprettyxml(indent="  "))


def create_nfo_for_channel(channel_data: NebulaChannelVideoContentDetails, channel_directory: Path) -> Path:
    channel_nfo_file_path = channel_directory / "tvshow.nfo"
    with open(channel_nfo_file_path, "w") as file:
        channel_details_dict = {
            "plot": channel_data.description,
            "title": channel_data.title
        }
        file.write(parseString(dicttoxml.dicttoxml(channel_details_dict, attr_type=False, custom_root="channeldetails")).toprettyxml(indent="  "))