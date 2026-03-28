import json
import logging
from pathlib import Path

from models.nebula.Channel import NebulaChannelVideoContentDetails
from models.nebula.Fetched import NebulaChannelVideoContentResponseModel, NebulaChannelVideoContentEpisodes


def get_channel_info_from_db(channel_slug: str, output_directory: Path):
    channel_directory = output_directory / channel_slug
    logging.info(f"Fetching channel info for channel {channel_slug} from {channel_directory}")
    if not channel_directory.exists():
        raise FileNotFoundError(f"Channel {channel_slug} not found, please create it first")
    with open(channel_directory / "episodes.json", "r") as episodes:
        episode_list = json.load(episodes)
    with open(channel_directory / "channel.json", "r") as channel:
        channel_data = json.load(channel)
    episode_object = NebulaChannelVideoContentEpisodes(next=None, previous=None, results=episode_list)
    channel_object = NebulaChannelVideoContentDetails(**channel_data)
    return NebulaChannelVideoContentResponseModel(details=channel_object, episodes=episode_object)