from urllib.parse import unquote

from requests import get as requests_get
import logging
from models.urls import NEBULA_API_CONTENT_ALL_VIDEOS
from models.nebula.Fetched import NebulaChannelVideoContentEpisodes


def get_all_channels_slugs_from_video_feed(
    authorization_header: str,
    category_feed_selector: str | None = None,
    cursor_times_limit_fetch_maximum: int = 100,
) -> list[str]:
    response = requests_get(
        url=unquote(str(NEBULA_API_CONTENT_ALL_VIDEOS)).format(
            CATEGORY_QUERY=f"?category={category_feed_selector}"
            if category_feed_selector is not None
            else ""
        ),
        headers={"Authorization": authorization_header},
    )
    if response.status_code == 200:
        data = NebulaChannelVideoContentEpisodes(**response.json())
        logging.info(
            "Received %s episodes from the initial video feed request",
            len(data.results),
        )
        cursor_times = 0
        while data.next is not None and cursor_times < cursor_times_limit_fetch_maximum:
            response = requests_get(
                url=data.next,
                headers={
                    "Authorization": authorization_header,
                },
            )
            if response.status_code == 200:
                cursoredData = NebulaChannelVideoContentEpisodes(**response.json())
                logging.info(
                    "Received %s episodes from the video feed for page #%s (total episodes: %s)",
                    len(cursoredData.results),
                    cursor_times,
                    len(data.results),
                )
                data.results.extend(cursoredData.results)
                data.next = cursoredData.next
                cursor_times += 1
                continue
            raise Exception(
                f"Failed to get video feed for the page #{cursor_times}: `{response.content}` with status code {response.status_code}"
            )
        channels = list({x.channel_slug for x in data.results})
        logging.info(
            "Found %s channels in video feed in the last %s pages with %s episodes%s",
            len(channels),
            cursor_times,
            len(data.results),
            f" for category `{category_feed_selector}`"
            if category_feed_selector is not None
            else "",
        )
        logging.debug("Found channels: %s", channels)
        return (
            channels  # if not okShouldReturnAllEpisodesListActually else data.results
        )
    raise Exception(
        f"Failed to get video feed: `{response.content}` with status code {response.status_code}"
    )
