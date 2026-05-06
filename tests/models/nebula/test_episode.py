import pytest
from pydantic import ValidationError

from models.nebula.episode import (
    NebulaChannelVideoContentEpisodeResult,
    NebulaChannelVideoContentEpisodeResultImageInformation,
    NebulaChannelVideoContentEpisodeResultImages,
    NebulaChannelVideoContentEpisodeResultAssets,
)
from models.nebula.video_attributes import VideoNebulaAttributes


def _image_info():
    return {
        "formats": ["webp", "jpeg"],
        "width": 128,
        "height": 128,
        "src": "https://example.com/img.jpg",
    }


def _episode_payload(**overrides):
    base = {
        "id": "ep-id",
        "type": "video_episode",
        "slug": "ep-slug",
        "title": "Title",
        "description": "Desc",
        "short_description": None,
        "duration": 120,
        "duration_to_complete": 120,
        "published_at": "2024-01-01T00:00:00Z",
        "episode_url": None,
        "channel_id": "ch-id",
        "channel_slug": "ch-slug",
        "channel_slugs": ["ch-slug"],
        "channel_title": "Channel",
        "category_slugs": ["news"],
        "assets": {"channel_avatar": {}, "thumbnail": {}},
        "images": {
            "channel_avatar": _image_info(),
            "thumbnail": _image_info(),
        },
        "attributes": ["is_nebula_plus"],
        "share_url": "https://nebula.tv/ep",
    }
    base.update(overrides)
    return base


def test_image_information_parses():
    info = NebulaChannelVideoContentEpisodeResultImageInformation(**_image_info())
    assert info.formats == ["webp", "jpeg"]
    assert info.width == 128
    assert info.height == 128


def test_image_information_invalid_url_raises():
    payload = _image_info()
    payload["src"] = "not-a-url"
    with pytest.raises(ValidationError):
        NebulaChannelVideoContentEpisodeResultImageInformation(**payload)


def test_images_wrapper_parses():
    img = NebulaChannelVideoContentEpisodeResultImages(
        channel_avatar=_image_info(), thumbnail=_image_info()
    )
    assert img.thumbnail.width == 128


def test_assets_accepts_arbitrary_dict():
    assets = NebulaChannelVideoContentEpisodeResultAssets(
        channel_avatar={"a": 1}, thumbnail={"b": 2}
    )
    assert assets.channel_avatar == {"a": 1}
    assert assets.thumbnail == {"b": 2}


def test_episode_result_parses_full_payload():
    ep = NebulaChannelVideoContentEpisodeResult(**_episode_payload())
    assert ep.slug == "ep-slug"
    assert ep.attributes == [VideoNebulaAttributes.IS_NEBULA_PLUS]
    assert ep.duration == 120


def test_episode_result_negative_duration_raises():
    with pytest.raises(ValidationError):
        NebulaChannelVideoContentEpisodeResult(**_episode_payload(duration=-1))


def test_episode_result_unknown_attribute_raises():
    with pytest.raises(ValidationError):
        NebulaChannelVideoContentEpisodeResult(**_episode_payload(attributes=["bogus"]))


def test_episode_result_optional_fields_default_none():
    ep = NebulaChannelVideoContentEpisodeResult(**_episode_payload())
    assert ep.description == "Desc"
    assert ep.episode_url is None
    assert ep.channel is None
    assert ep.zype_id is None
    assert ep.engagement is None


def test_episode_result_missing_required_field_raises():
    payload = _episode_payload()
    del payload["id"]
    with pytest.raises(ValidationError):
        NebulaChannelVideoContentEpisodeResult(**payload)
