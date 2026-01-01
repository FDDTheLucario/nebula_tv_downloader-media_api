from pydantic import BaseModel, HttpUrl, NonNegativeInt
from models.nebula.VideoAttributes import VideoNebulaAttributes


class NebulaChannelVideoContentEpisodeResultImageInformation(BaseModel):
    formats: list[str]
    width: int
    height: int
    src: HttpUrl


class NebulaChannelVideoContentEpisodeResultImages(BaseModel):
    channel_avatar: NebulaChannelVideoContentEpisodeResultImageInformation
    thumbnail: NebulaChannelVideoContentEpisodeResultImageInformation


class NebulaChannelVideoContentEpisodeResultAssets(BaseModel):
    channel_avatar: dict
    thumbnail: dict


class NebulaChannelVideoContentEpisodeResult(BaseModel):
    id: str
    type: str
    slug: str
    title: str
    description: str | None = None
    short_description: str | None = None
    duration: NonNegativeInt
    duration_to_complete: NonNegativeInt
    published_at: str
    episode_url: HttpUrl | None = None
    channel_id: str
    channel_slug: str
    channel_slugs: list[str]
    channel_title: str
    category_slugs: list[str]
    assets: NebulaChannelVideoContentEpisodeResultAssets
    images: NebulaChannelVideoContentEpisodeResultImages
    attributes: list[VideoNebulaAttributes]
    share_url: str
    channel: HttpUrl | None = None
    engagement: dict | None = None
    zype_id: str | None = None
