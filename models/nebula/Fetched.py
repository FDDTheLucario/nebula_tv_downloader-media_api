from pydantic import BaseModel, HttpUrl
from models.nebula.Episode import NebulaChannelVideoContentEpisodeResult
from models.nebula.Channel import NebulaChannelVideoContentDetails


class NebulaChannelVideoContentEpisodes(BaseModel):
    next: HttpUrl | None = None
    previous: HttpUrl | None = None
    results: list[NebulaChannelVideoContentEpisodeResult]


class NebulaChannelVideoContentResponseModel(BaseModel):
    details: NebulaChannelVideoContentDetails
    episodes: NebulaChannelVideoContentEpisodes
