from typing import Generator
from models.configuration import ConfigurationNebulaFiltersModel
from models.nebula.Episode import NebulaChannelVideoContentEpisodeResult
from models.nebula.VideoAttributes import VideoNebulaAttributes
import logging


def filter_out_episodes(
    filter_settings: ConfigurationNebulaFiltersModel,
    episodes: list[NebulaChannelVideoContentEpisodeResult],
) -> Generator[NebulaChannelVideoContentEpisodeResult, None, None]:
    applicable_filters: list[VideoNebulaAttributes] = []
    if filter_settings.INCLUDE_NEBULA_ORIGINALS:
        applicable_filters.append(VideoNebulaAttributes.IS_NEBULA_ORIGINAL)
    if filter_settings.INCLUDE_NEBULA_PLUS:
        applicable_filters.append(VideoNebulaAttributes.IS_NEBULA_PLUS)
    if filter_settings.INCLUDE_NEBULA_FIRST:
        applicable_filters.append(VideoNebulaAttributes.IS_NEBULA_FIRST)
    logging.debug("Applicable filters: %s", applicable_filters)
    logging.debug("Include regular videos: %s", filter_settings.INCLUDE_REGULAR_VIDEOS)
    for episode in episodes:
        if applicable_filters and any(
            filter in episode.attributes for filter in applicable_filters
        ):
            yield episode
            continue
        if filter_settings.INCLUDE_REGULAR_VIDEOS and (
            not episode.attributes
            or [VideoNebulaAttributes.FREE_SAMPLE_ELIGIBLE] == episode.attributes
        ):
            yield episode
            continue
        continue
