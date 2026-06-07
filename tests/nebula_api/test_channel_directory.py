from http import HTTPStatus
from urllib.parse import unquote

import pytest

from models.urls import NEBULA_API_CONTENT_VIDEO_CHANNELS_DIRECTORY
from nebula_api.channel_directory import get_channel_directory

DIRECTORY_URL = unquote(str(NEBULA_API_CONTENT_VIDEO_CHANNELS_DIRECTORY))
PAGE2_URL = "https://content.api.nebula.app/video/channels/?offset=20&page_size=20"
PAGE3_URL = "https://content.api.nebula.app/video/channels/?offset=40&page_size=20"
AUTH = "Bearer test"


def _result(slug, title=None):
    return {"slug": slug, "title": title or slug, "type": "video_channel"}


def _page(*slugs, next_url=None):
    return {
        "next": next_url,
        "previous": None,
        "results": [_result(s) for s in slugs],
    }


def test_get_channel_directory_single_page(requests_mock):
    requests_mock.get(
        DIRECTORY_URL,
        status_code=HTTPStatus.OK,
        json=_page("a", "b"),
    )
    results = get_channel_directory(AUTH)
    assert [r.slug for r in results] == ["a", "b"]
    assert requests_mock.call_count == 1


def test_get_channel_directory_follows_next(requests_mock):
    requests_mock.get(
        DIRECTORY_URL, status_code=HTTPStatus.OK, json=_page("a", "b", next_url=PAGE2_URL)
    )
    requests_mock.get(PAGE2_URL, status_code=HTTPStatus.OK, json=_page("c"))
    results = get_channel_directory(AUTH)
    assert [r.slug for r in results] == ["a", "b", "c"]
    assert requests_mock.call_count == 2


def test_get_channel_directory_respects_max_pages(requests_mock):
    requests_mock.get(
        DIRECTORY_URL, status_code=HTTPStatus.OK, json=_page("a", next_url=PAGE2_URL)
    )
    requests_mock.get(
        PAGE2_URL, status_code=HTTPStatus.OK, json=_page("b", next_url=PAGE3_URL)
    )
    requests_mock.get(PAGE3_URL, status_code=HTTPStatus.OK, json=_page("c"))
    results = get_channel_directory(AUTH, max_pages=2)
    assert [r.slug for r in results] == ["a", "b"]
    assert requests_mock.call_count == 2


def test_get_channel_directory_non_200_raises(requests_mock):
    requests_mock.get(DIRECTORY_URL, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
    with pytest.raises(Exception, match="500"):
        get_channel_directory(AUTH)


def test_get_channel_directory_non_200_mid_pagination_raises(requests_mock):
    requests_mock.get(
        DIRECTORY_URL, status_code=HTTPStatus.OK, json=_page("a", next_url=PAGE2_URL)
    )
    requests_mock.get(PAGE2_URL, status_code=HTTPStatus.SERVICE_UNAVAILABLE)
    with pytest.raises(Exception, match="503"):
        get_channel_directory(AUTH)
