from http import HTTPStatus
from wsgiref import headers

import pytest

from nebula_api.ChannelVideos import get_channel_video_content
import tests.consts


def test_get_channel_video_content_no_next_page(requests_mock):
    requests_mock.get(
        url=tests.consts.CHANNEL_VIDEO_GET_URL,
        status_code=HTTPStatus.OK,
        headers={
            'Authorization': tests.consts.FULL_AUTH_TOKEN
        },
        json=tests.consts.CHANNEL_VIDEO_CONTENT_NO_NEXT_PAGE
    )

    channel_video_content = get_channel_video_content('nilered', tests.consts.FULL_AUTH_TOKEN)
    assert channel_video_content is not None
    assert len(channel_video_content.episodes.results) == 20
    assert requests_mock.call_count == 1

def test_get_channel_video_content_with_next_page(requests_mock):
    requests_mock.get(
        tests.consts.CHANNEL_VIDEO_GET_URL, [
            {'status_code': HTTPStatus.OK, 'json': tests.consts.CHANNEL_VIDEO_CONTENT_NEXT_PAGE, 'headers':{'Authorization': tests.consts.FULL_AUTH_TOKEN}},
            {'status_code': HTTPStatus.OK, 'json': tests.consts.CHANNEL_VIDEO_CONTENT_NO_NEXT_PAGE, 'headers':{'Authorization': tests.consts.FULL_AUTH_TOKEN}},
        ]
    )

    channel_video_content = get_channel_video_content('nilered', tests.consts.FULL_AUTH_TOKEN)
    assert channel_video_content is not None
    assert len(channel_video_content.episodes.results) == 40
    assert requests_mock.call_count == 2

def test_get_channel_video_content_rate_limit_verify_graceful_handling(requests_mock):
    requests_mock.get(
        tests.consts.CHANNEL_VIDEO_GET_URL, [
            {'status_code': HTTPStatus.OK, 'json': tests.consts.CHANNEL_VIDEO_CONTENT_NEXT_PAGE, 'headers':{'Authorization': tests.consts.FULL_AUTH_TOKEN}},
            {'status_code': HTTPStatus.TOO_MANY_REQUESTS, 'headers':{'Authorization': tests.consts.FULL_AUTH_TOKEN}},
            {'status_code': HTTPStatus.OK, 'json': tests.consts.CHANNEL_VIDEO_CONTENT_NO_NEXT_PAGE, 'headers':{'Authorization': tests.consts.FULL_AUTH_TOKEN}},
        ]
    )
    channel_video_content = get_channel_video_content('nilered', tests.consts.FULL_AUTH_TOKEN)
    assert channel_video_content is not None
    assert len(channel_video_content.episodes.results) == 40
    assert requests_mock.call_count == 3

def test_get_channel_video_content_unexpected_error_verify_exception_bubbles(requests_mock):
    requests_mock.get(
        url=tests.consts.CHANNEL_VIDEO_GET_URL,
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        headers={'Authorization': tests.consts.FULL_AUTH_TOKEN},
        text='Internal Server Error'
    )
    with pytest.raises(Exception) as e:
        get_channel_video_content('nilered', tests.consts.FULL_AUTH_TOKEN)
    assert str(e.value) ==  f"Failed to get channel video content for `nilered`: `b'Internal Server Error'` with status code 500"
