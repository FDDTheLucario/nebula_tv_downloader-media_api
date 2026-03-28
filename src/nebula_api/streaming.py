from http import HTTPStatus
from urllib.parse import unquote

from requests import get as requests_get
import logging
from time import sleep
from models.nebula.Streaming import NebulaVideoContentStreamingResponseModel
from models.urls import NEBULA_API_VIDEO_STREAM_INFORMATION


def get_streaming_information_by_episode(
        video_slug: str,
        authorization_header: str,
        retry_after_unsuccessful_seconds: int = 5,
) -> NebulaVideoContentStreamingResponseModel:
    response = requests_get(
        url = unquote(
            str(NEBULA_API_VIDEO_STREAM_INFORMATION)
        ).format(VIDEO_SLUG = video_slug), headers= {
            "Authorization": authorization_header,
        },
    )

    logging.debug(
        "Received response of `%s...` with status code %s in %s seconds",
        response.content[:20],
        response.status_code,
        response.elapsed.total_seconds(),
    )
    if response.status_code == HTTPStatus.OK:
        return NebulaVideoContentStreamingResponseModel(**response.json())
    elif response.status_code == HTTPStatus.UNAUTHORIZED:
        logging.info(
            "The authorization token is invalid (got restricted), retrying in %s seconds... (status code: %s) (you should probably buy a new subscription or contact support)",
            retry_after_unsuccessful_seconds,
            response.status_code,
        )
        sleep(retry_after_unsuccessful_seconds)
        return get_streaming_information_by_episode(
            video_slug=video_slug,
            authorization_header=authorization_header,
            retry_after_unsuccessful_seconds=10,
        )
    elif response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        logging.warning(
            "Throttled by Nebula API while getting streaming information for `%s`, waiting for %s seconds...",
            video_slug,
            retry_after_unsuccessful_seconds,
        )
        sleep(retry_after_unsuccessful_seconds)
        return get_streaming_information_by_episode(
            video_slug=video_slug,
            authorization_header=authorization_header,
            retry_after_unsuccessful_seconds=retry_after_unsuccessful_seconds + 1,
        )
    raise Exception(
        f"Failed to get video streaming info for `{video_slug}` for an unknown reason: `{response.content[:32]}...` with status code {response.status_code}"
    )
