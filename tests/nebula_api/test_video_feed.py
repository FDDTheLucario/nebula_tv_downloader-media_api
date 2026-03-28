from http import HTTPStatus

import pytest

import tests.consts
from nebula_api.video_feed import get_all_channels_slugs_from_video_feed


def test_get_all_channels_slugs_from_video_feed_category_below_cursor_max(requests_mock):
    requests_mock.get(
        tests.consts.GET_ALL_VIDEOS_CATEGORY,
        [{"headers": {"Authorization": tests.consts.FULL_AUTH_TOKEN},
          "status_code": HTTPStatus.OK, "json": tests.consts.NEBULA_CHANNEL_VIDEO_CONTENT_EPISODES_WITH_CATEGORY},
         {"headers": {"Authorization": tests.consts.FULL_AUTH_TOKEN},
          "status_code": HTTPStatus.OK, "json": tests.consts.NEBULA_CHANNEL_VIDEO_CONTENT_EPISODES_WITH_CATEGORY},
         {"headers": {"Authorization": tests.consts.FULL_AUTH_TOKEN}, "status_code": HTTPStatus.OK,
          "json": tests.consts.NEBULA_CHANNEL_VIDEO_CONTENT_EPISODES_WITH_CATEGORY_NO_NEXT}]
    )

    channels = get_all_channels_slugs_from_video_feed(tests.consts.FULL_AUTH_TOKEN, "news", 2)
    assert sorted(channels) == sorted(
        ['simonclark', 'eumadesimple', 'tldrnewsuk', 'exploringhistory', 'tldrnewsglobal', 'tfc', 'brewmarkets',
         'legaleagle', 'morningbrewdaily'])
    assert requests_mock.call_count == 3


def test_get_all_channels_slugs_from_video_feed_category_above_cursor_max(requests_mock):
    requests_mock.get(
        tests.consts.GET_ALL_VIDEOS_CATEGORY,
        [{"headers": {"Authorization": tests.consts.FULL_AUTH_TOKEN},
          "status_code": HTTPStatus.OK, "json": tests.consts.NEBULA_CHANNEL_VIDEO_CONTENT_EPISODES_WITH_CATEGORY},
         {"headers": {"Authorization": tests.consts.FULL_AUTH_TOKEN},
          "status_code": HTTPStatus.OK, "json": tests.consts.NEBULA_CHANNEL_VIDEO_CONTENT_EPISODES_WITH_CATEGORY},
         {"headers": {"Authorization": tests.consts.FULL_AUTH_TOKEN},
          "status_code": HTTPStatus.OK, "json": tests.consts.NEBULA_CHANNEL_VIDEO_CONTENT_EPISODES_WITH_CATEGORY},
         {"headers": {"Authorization": tests.consts.FULL_AUTH_TOKEN},
          "status_code": HTTPStatus.OK, "json": tests.consts.NEBULA_CHANNEL_VIDEO_CONTENT_EPISODES_WITH_CATEGORY},
         {"headers": {"Authorization": tests.consts.FULL_AUTH_TOKEN}, "status_code": HTTPStatus.OK,
          "json": tests.consts.NEBULA_CHANNEL_VIDEO_CONTENT_EPISODES_WITH_CATEGORY_NO_NEXT}]
    )

    channels = get_all_channels_slugs_from_video_feed(tests.consts.FULL_AUTH_TOKEN, "news", 2)
    assert sorted(channels) == sorted(
        ['simonclark', 'eumadesimple', 'tldrnewsuk', 'exploringhistory', 'tldrnewsglobal', 'tfc', 'brewmarkets',
         'legaleagle', 'morningbrewdaily'])
    assert requests_mock.call_count == 3


def test_get_all_channels_slugs_from_video_feed_category_unexpected_exception_on_first_call_verify_exception_bubbles(
        requests_mock):
    requests_mock.get(
        url=tests.consts.GET_ALL_VIDEOS_CATEGORY,
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        headers={"Authorization": tests.consts.FULL_AUTH_TOKEN},
        text='Internal Server Error'
    )

    with pytest.raises(Exception) as e:
        get_all_channels_slugs_from_video_feed(tests.consts.FULL_AUTH_TOKEN, "news", 2)
    assert str(e.value) == f"Failed to get video feed: `b'Internal Server Error'` with status code 500"


def test_get_all_channels_slugs_from_video_feed_no_category_verify_url_has_no_category(requests_mock):
    requests_mock.get(
        tests.consts.GET_ALL_VIDEOS_NO_CATEGORY,
        [{'status_code': HTTPStatus.OK,
          'headers': {"Authorization": tests.consts.FULL_AUTH_TOKEN},
          'json': tests.consts.NEBULA_CHANNEL_VIDEO_CONTENT_EPISODES_NO_CATEGORY
          }, {
             'status_code': HTTPStatus.OK,
             'headers': {"Authorization": tests.consts.FULL_AUTH_TOKEN},
             'json': tests.consts.NEBULA_CHANNEL_VIDEO_CONTENT_EPISODES_NO_CATEGORY_NO_NEXT
         }]
    )

    channels = get_all_channels_slugs_from_video_feed(tests.consts.FULL_AUTH_TOKEN, "news")
    assert requests_mock.call_count == 2
    assert sorted(channels) == sorted(
        ['bobbybroccoli', 'jose', 'maryspender', 'isaacarthur', 'rifftrax', 'foreignfridays', 'tldrnewsglobal',
         'mywildbackyard', 'angelacollier', 'exploringhistory', 'womancarryingman', 'occ', 'mancarryingthing',
         'jaredhenderson', 'chefpk', 'georgiadow', 'thenandocut', 'reneritchie'])


def test_get_all_channels_slugs_from_video_feed_error_when_cursoring_verify_exception_bubbles(requests_mock):
    requests_mock.get(
        [{'url':tests.consts.GET_ALL_VIDEOS_NO_CATEGORY,
        'status_code': HTTPStatus.OK, 'headers': {"Authorization": tests.consts.FULL_AUTH_TOKEN},
          'json': tests.consts.NEBULA_CHANNEL_VIDEO_CONTENT_EPISODES_NO_CATEGORY}
            ,
         {'url':f'{tests.consts.GET_ALL_VIDEOS_NO_CATEGORY}?offset=20&page_size=20','status_code': HTTPStatus.INTERNAL_SERVER_ERROR, 'headers': {"Authorization": tests.consts.FULL_AUTH_TOKEN},
          'text': 'Internal Server Error'}],
    )
    with pytest.raises(Exception) as e:
        get_all_channels_slugs_from_video_feed(tests.consts.FULL_AUTH_TOKEN, None, 2)

    assert str(e.value) == f"Failed to get video feed for the page #1: `b'Internal Server Error'` with status code 500"
