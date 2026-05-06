import json
import logging
from pathlib import Path

from models.nebula.channel import NebulaChannelVideoContentDetails
from models.nebula.fetched import (
    NebulaChannelVideoContentEpisodes,
    NebulaChannelVideoContentResponseModel,
)

CHANNEL_FILENAME = "channel.json"
EPISODES_FILENAME = "episodes.json"


def _channel_dir(channel_slug: str, output_directory: Path) -> Path:
    return output_directory / channel_slug


def save_channel_info(
    channel_slug: str,
    channel_data: NebulaChannelVideoContentDetails,
    episodes_data: NebulaChannelVideoContentEpisodes,
    output_directory: Path,
) -> Path:
    channel_directory = _channel_dir(channel_slug, output_directory)
    channel_directory.mkdir(parents=True, exist_ok=True)
    logging.info("Saving channel info for `%s` to %s", channel_slug, channel_directory)
    (channel_directory / CHANNEL_FILENAME).write_text(
        json.dumps(channel_data.model_dump(), indent=4, default=str)
    )
    (channel_directory / EPISODES_FILENAME).write_text(
        json.dumps(episodes_data.model_dump()["results"], indent=4, default=str)
    )
    return channel_directory


def load_channel_info(
    channel_slug: str, output_directory: Path
) -> NebulaChannelVideoContentResponseModel:
    channel_directory = _channel_dir(channel_slug, output_directory)
    logging.info("Loading channel info for `%s` from %s", channel_slug, channel_directory)
    if not channel_directory.exists():
        raise FileNotFoundError(
            f"Channel {channel_slug} not found, please create it first"
        )
    episodes_payload = json.loads((channel_directory / EPISODES_FILENAME).read_text())
    channel_payload = json.loads((channel_directory / CHANNEL_FILENAME).read_text())
    return NebulaChannelVideoContentResponseModel(
        details=NebulaChannelVideoContentDetails(**channel_payload),
        episodes=NebulaChannelVideoContentEpisodes(
            next=None, previous=None, results=episodes_payload
        ),
    )
