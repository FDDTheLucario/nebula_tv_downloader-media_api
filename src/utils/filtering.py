from typing import Generator
from models.configuration import ConfigurationNebulaFiltersModel
from models.nebula.episode import NebulaChannelVideoContentEpisodeResult
from models.nebula.video_attributes import VideoNebulaAttributes
import logging


def filter_out_episodes(
    filter_settings: ConfigurationNebulaFiltersModel,
    episodes: list[NebulaChannelVideoContentEpisodeResult],
) -> Generator[NebulaChannelVideoContentEpisodeResult, None, None]:
    applicable_filters: list[VideoNebulaAttributes] = []
    if filter_settings.include_nebula_originals:
        applicable_filters.append(VideoNebulaAttributes.IS_NEBULA_ORIGINAL)
    if filter_settings.include_nebula_plus:
        applicable_filters.append(VideoNebulaAttributes.IS_NEBULA_PLUS)
    if filter_settings.include_nebula_first:
        applicable_filters.append(VideoNebulaAttributes.IS_NEBULA_FIRST)
    logging.debug("Applicable filters: %s", applicable_filters)
    logging.debug("Include regular videos: %s", filter_settings.include_regular_videos)
    for episode in episodes:
        if applicable_filters and any(
            filter in episode.attributes for filter in applicable_filters
        ):
            yield episode
            continue
        if filter_settings.include_regular_videos and (
            not episode.attributes
            or [VideoNebulaAttributes.FREE_SAMPLE_ELIGIBLE] == episode.attributes
        ):
            yield episode
            continue
        continue
