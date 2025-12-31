from datetime import datetime
import json
from pathlib import Path
from xml.dom.minidom import parseString

import dicttoxml

from models.nebula.Channel import NebulaChannelVideoContentDetails
from models.nebula.Episode import NebulaChannelVideoContentEpisodeResult
from models.nebula.Fetched import NebulaChannelVideoContentEpisodes


def create_channel_subdirectory_and_store_metadata_information(
    channelSlug: str,
    channelData: NebulaChannelVideoContentDetails,
    episodesData: NebulaChannelVideoContentEpisodes,
    outputDirectory: Path,
) -> Path:
    channelDirectory = outputDirectory / channelSlug
    channelDirectory.mkdir(parents=True, exist_ok=True)
    with open(channelDirectory / "channel.json", "w") as file:
        json.dump(channelData.dict(), file, indent=4)
    with open(channelDirectory / "episodes.json", "w") as file:
        json.dump(episodesData.dict()["results"], file, indent=4)
    return channelDirectory


def create_nfo_for_video(episode: NebulaChannelVideoContentEpisodeResult, episodeDirectory: Path) -> Path:
    videoNfoFilePath = episodeDirectory / f"{episode.slug}.nfo"
    episodeDate = datetime.fromisoformat(episode.published_at)
    print(videoNfoFilePath)
    with open(videoNfoFilePath, "w") as file:
        episodeDetailsDict = {
            "title": episode.title,
            "showtitle": episode.channel_title,
            "plot": episode.description,
            "unique_id": episode.id,
            "premiered": episodeDate.strftime("%Y-%m-%d"),
            "season": episodeDate.year
        }
        file.write(parseString(dicttoxml.dicttoxml(episodeDetailsDict, attr_type=False, custom_root="episodedetails")).toprettyxml(indent="  "))


def create_nfo_for_channel(channelData: NebulaChannelVideoContentDetails, channelDirectory: Path) -> Path:
    channelNfoFilePath = channelDirectory / "tvshow.nfo"
    with open(channelNfoFilePath, "w") as file:
        channelDetailsDict = {
            "plot": channelData.description,
            "title": channelData.title
        }
        file.write(parseString(dicttoxml.dicttoxml(channelDetailsDict, attr_type=False, custom_root="channeldetails")).toprettyxml(indent="  "))