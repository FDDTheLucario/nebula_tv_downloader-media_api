import logging
from http import HTTPStatus
from urllib.parse import unquote

from requests import get as requests_get

from models.nebula.channel_directory import (
    NebulaChannelDirectoryResponse,
    NebulaChannelDirectoryResult,
)
from models.urls import NEBULA_API_CONTENT_VIDEO_CHANNELS_DIRECTORY


def get_channel_directory(
    authorization_header: str,
    max_pages: int = 50,
) -> list[NebulaChannelDirectoryResult]:
    """Walk the full Nebula channel directory, following `next` until exhausted
    or max_pages reached. Returns all channel summary results (unsorted)."""
    response = requests_get(
        url=unquote(str(NEBULA_API_CONTENT_VIDEO_CHANNELS_DIRECTORY)),
        headers={"Authorization": authorization_header},
    )
    if response.status_code != HTTPStatus.OK:
        raise Exception(
            f"Failed to get channel directory: `{response.content}` "
            f"with status code {response.status_code}"
        )

    data = NebulaChannelDirectoryResponse.model_validate(response.json())
    results = list(data.results)
    pages = 1
    while data.next is not None and pages < max_pages:
        response = requests_get(
            url=str(data.next),
            headers={"Authorization": authorization_header},
        )
        if response.status_code != HTTPStatus.OK:
            raise Exception(
                f"Failed to get channel directory page #{pages}: "
                f"`{response.content}` with status code {response.status_code}"
            )
        page = NebulaChannelDirectoryResponse.model_validate(response.json())
        results.extend(page.results)
        data.next = page.next
        pages += 1

    if data.next is not None:
        logging.info(
            "Channel directory truncated at max_pages=%s; more pages available",
            max_pages,
        )
    logging.info(
        "Found %s channels in the directory across %s pages", len(results), pages
    )
    return results
