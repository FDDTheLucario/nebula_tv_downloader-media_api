import pytest
from pydantic import ValidationError

from models.nebula.channel import (
    NebulaChannelVideoContentDetails,
    NebulaChannelVideoContentDetailsAssets,
    NebulaChannelVideoContentDetailsCategory,
    NebulaChannelVideoContentDetailsPlaylist,
)


def _category():
    return {
        "id": "cat-id",
        "type": "category",
        "slug": "news",
        "title": "News",
        "assets": {},
        "images": {},
    }


def _playlist():
    return {
        "id": "pl-id",
        "type": "playlist",
        "slug": "pl",
        "title": "Playlist",
    }


def _channel_payload(**overrides):
    base = {
        "id": "ch-id",
        "type": "channel",
        "slug": "ch-slug",
        "title": "Channel",
        "published_at": "2024-01-01T00:00:00Z",
        "description": "Desc",
        "assets": {},
        "images": {},
        "genre_category_title": "News",
        "genre_category_slug": "news",
        "categories": [_category()],
        "playlists": [_playlist()],
    }
    base.update(overrides)
    return base


def test_assets_optional_all_default_none():
    a = NebulaChannelVideoContentDetailsAssets()
    assert a.avatar is None
    assert a.banner is None
    assert a.hero is None
    assert a.featured is None


def test_assets_accepts_dicts():
    a = NebulaChannelVideoContentDetailsAssets(avatar={"src": "x"})
    assert a.avatar == {"src": "x"}


def test_category_parses():
    c = NebulaChannelVideoContentDetailsCategory(**_category())
    assert c.slug == "news"


def test_playlist_parses():
    p = NebulaChannelVideoContentDetailsPlaylist(**_playlist())
    assert p.slug == "pl"


def test_channel_details_parses_minimal():
    ch = NebulaChannelVideoContentDetails(**_channel_payload())
    assert ch.slug == "ch-slug"
    assert ch.website is None
    assert len(ch.categories) == 1
    assert len(ch.playlists) == 1


def test_channel_details_optional_social_urls_validated_when_provided():
    payload = _channel_payload(twitter="not-a-url")
    with pytest.raises(ValidationError):
        NebulaChannelVideoContentDetails(**payload)


def test_channel_details_accepts_valid_social_urls():
    payload = _channel_payload(
        website="https://example.com/",
        twitter="https://twitter.com/x",
    )
    ch = NebulaChannelVideoContentDetails(**payload)
    assert str(ch.website) == "https://example.com/"
    assert str(ch.twitter) == "https://twitter.com/x"


def test_channel_details_missing_required_field_raises():
    payload = _channel_payload()
    del payload["title"]
    with pytest.raises(ValidationError):
        NebulaChannelVideoContentDetails(**payload)
