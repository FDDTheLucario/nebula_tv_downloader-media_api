from datetime import datetime
from pathlib import Path
from xml.dom.minidom import parseString

import dicttoxml

from models.nebula.channel import NebulaChannelVideoContentDetails
from models.nebula.episode import NebulaChannelVideoContentEpisodeResult


def _write_nfo(path: Path, root: str, payload: dict) -> None:
    xml = parseString(
        dicttoxml.dicttoxml(payload, attr_type=False, custom_root=root)
    ).toprettyxml(indent="  ")
    path.write_text(xml)


def create_nfo_for_video(
    episode: NebulaChannelVideoContentEpisodeResult, episode_directory: Path
) -> None:
    episode_date = datetime.fromisoformat(episode.published_at)
    _write_nfo(
        episode_directory / f"{episode.slug}.nfo",
        "episodedetails",
        {
            "title": episode.title,
            "showtitle": episode.channel_title,
            "plot": episode.description,
            "unique_id": episode.id,
            "premiered": episode_date.strftime("%Y-%m-%d"),
            "season": episode_date.year,
        },
    )


def create_nfo_for_channel(
    channel_data: NebulaChannelVideoContentDetails, channel_directory: Path
) -> None:
    _write_nfo(
        channel_directory / "tvshow.nfo",
        "channeldetails",
        {"plot": channel_data.description, "title": channel_data.title},
    )
