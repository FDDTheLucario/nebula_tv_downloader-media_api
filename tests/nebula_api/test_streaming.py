import json
from http import HTTPStatus

import pytest

import consts
import tests.consts
from src.nebula_api.streaming import get_streaming_information_by_episode


def test_get_streaming_information_by_episode_return_manifest(requests_mock):
    requests_mock.get(
        url=tests.consts.STREAMING_INFO_GET_URL,
        status_code=HTTPStatus.OK,
        json=json.loads(consts.VIDEO_CONTENT_STREAMING_RESPONSE),
        headers={"Authorization": f"{tests.consts.FULL_AUTH_TOKEN}"},
    )
    streaming_information = get_streaming_information_by_episode(video_slug="slug",
                                                                 authorization_header=tests.consts.FULL_AUTH_TOKEN)

    assert streaming_information is not None
    assert streaming_information.manifest == tests.consts.MANIFEST
    assert streaming_information.subtitles.__len__() == 1


def test_get_streaming_information_by_episode_unauthorized_verify_and_success_verify_sleep(requests_mock):
    requests_mock.get(
        tests.consts.STREAMING_INFO_GET_URL, [
            {
                'status_code': HTTPStatus.UNAUTHORIZED,
                'headers': {'Authorization': tests.consts.FULL_AUTH_TOKEN},
            },
            {
                'status_code': HTTPStatus.OK,
                'headers': {'Authorization': tests.consts.FULL_AUTH_TOKEN},
                'json': json.loads(consts.VIDEO_CONTENT_STREAMING_RESPONSE),
            }
        ],
    )
    streaming_information = get_streaming_information_by_episode(video_slug="slug",
                                                                 authorization_header=tests.consts.FULL_AUTH_TOKEN)
    assert streaming_information.manifest is not None
    assert streaming_information.subtitles.__len__() == 1
    assert streaming_information.manifest == tests.consts.MANIFEST

    assert requests_mock.call_count == 2


def test_get_streaming_information_by_episode_throttled_verify_and_success_verify_sleep(requests_mock):
    requests_mock.get(
        tests.consts.STREAMING_INFO_GET_URL, [
            {
                'status_code': HTTPStatus.TOO_MANY_REQUESTS,
                'headers': {'Authorization': tests.consts.FULL_AUTH_TOKEN},
            },
            {
                'status_code': HTTPStatus.OK,
                'headers': {'Authorization': tests.consts.FULL_AUTH_TOKEN},
                'json': json.loads(consts.VIDEO_CONTENT_STREAMING_RESPONSE),
            }
        ],
    )
    streaming_information = get_streaming_information_by_episode(video_slug="slug",
                                                                 authorization_header=tests.consts.FULL_AUTH_TOKEN)
    assert streaming_information.manifest is not None
    assert streaming_information.subtitles.__len__() == 1
    assert streaming_information.manifest == tests.consts.MANIFEST

    assert requests_mock.call_count == 2


def test_get_streaming_information_by_episode_unexpected_error_verify_exception_bubbles(requests_mock):
    requests_mock.get(
        url=tests.consts.STREAMING_INFO_GET_URL,
        status_code=HTTPStatus.BAD_REQUEST,
        headers={'Authorization': tests.consts.FULL_AUTH_TOKEN},
        text=tests.consts.BAD_REQUEST,
    )

    with pytest.raises(Exception) as e:
        get_streaming_information_by_episode(video_slug="slug", authorization_header=tests.consts.FULL_AUTH_TOKEN)

    assert str(e.value) == ('Failed to get video streaming info for `slug` for an unknown reason: '
 "`b'\\n<html>\\n<head><title>400 Bad Req'...` with status code 400")