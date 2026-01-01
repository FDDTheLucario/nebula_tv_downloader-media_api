from pydantic import BaseModel, HttpUrl


class NebulaChannelVideoContentDetailsAssets(BaseModel):
    avatar: dict | None = None
    banner: dict | None = None
    hero: dict | None = None
    featured: dict | None = None


class NebulaChannelVideoContentDetailsCategory(BaseModel):
    id: str
    type: str
    slug: str
    title: str
    assets: dict
    images: dict


class NebulaChannelVideoContentDetailsPlaylist(BaseModel):
    id: str
    type: str
    slug: str
    title: str


class NebulaChannelVideoContentDetails(BaseModel):
    id: str
    type: str
    slug: str
    title: str
    published_at: str
    description: str | None = None
    assets: NebulaChannelVideoContentDetailsAssets
    images: dict
    genre_category_title: str
    genre_category_slug: str
    categories: list[NebulaChannelVideoContentDetailsCategory]
    website: HttpUrl | None = None
    patreon: HttpUrl | None = None
    twitter: HttpUrl | None = None
    instagram: HttpUrl | None = None
    facebook: HttpUrl | None = None
    merch: HttpUrl | None = None
    merch_collection: str | None = None
    engagement: dict | None = None
    playlists: list[NebulaChannelVideoContentDetailsPlaylist]
    zype_id: str | None = None
