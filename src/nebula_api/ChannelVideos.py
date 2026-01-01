import logging
from http import HTTPStatus
from time import sleep
from urllib.parse import unquote

from requests import get as requests_get

from models.nebula.Fetched import NebulaChannelVideoContentResponseModel
from models.urls import NEBULA_API_CONTENT_VIDEO_CHANNELS


def get_channel_video_content(
        channel_slug: str, authorization_header: str, wait_after_unsuccessful_seconds: int = 5
) -> NebulaChannelVideoContentResponseModel:
    response = requests_get(
        url=unquote(str(NEBULA_API_CONTENT_VIDEO_CHANNELS)).format(CHANNEL_SLUG=channel_slug),
        headers={
            "Authorization": authorization_header,
        },
    )
    if response.status_code == HTTPStatus.OK:
        current_data = NebulaChannelVideoContentResponseModel(**response.json())
        logging.info(
            "Received %s videos from channel `%s` in the initial request",
            len(current_data.episodes.results),
            channel_slug,
        )
        current_cursor_times = 0
        while current_data.episodes.next is not None:
            response = requests_get(
                url=str(current_data.episodes.next),
                headers={
                    "Authorization": authorization_header,
                },
            )
            if response.status_code == HTTPStatus.OK:
                data = NebulaChannelVideoContentResponseModel(**response.json())
                logging.info(
                    "Received %s videos from channel `%s` from page #%s (total videos: %s)",
                    len(data.episodes.results),
                    channel_slug,
                    current_cursor_times,
                    len(current_data.episodes.results),
                )
                current_data.episodes.results.extend(data.episodes.results)
                current_data.episodes.next = data.episodes.next
                current_cursor_times += 1
                continue
            elif response.status_code == HTTPStatus.NOT_FOUND:
                logging.warning(
                    "Channel `%s` does not exist anymore",
                    channel_slug,
                )
                return current_data
            elif response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                logging.warning(
                    "Rate limit reached for channel `%s`, waiting %s seconds",
                    channel_slug,
                    wait_after_unsuccessful_seconds,
                )
                sleep(wait_after_unsuccessful_seconds)
                wait_after_unsuccessful_seconds *= 2
                continue
            raise Exception(
                f"Failed to get channel video content for page #{current_cursor_times} for `{channel_slug}`: `{response.content}` with status code {response.status_code}"
            )
        return current_data
    raise Exception(
        f"Failed to get channel video content for `{channel_slug}`: `{response.content}` with status code {response.status_code}"
    )
