from pydantic import BaseModel, HttpUrl
from models.nebula.episode import NebulaChannelVideoContentEpisodeResult
from models.nebula.channel import NebulaChannelVideoContentDetails


class NebulaChannelVideoContentEpisodes(BaseModel):
    next: HttpUrl | None = None
    previous: HttpUrl | None = None
    results: list[NebulaChannelVideoContentEpisodeResult]


class NebulaChannelVideoContentResponseModel(BaseModel):
    details: NebulaChannelVideoContentDetails
    episodes: NebulaChannelVideoContentEpisodes
