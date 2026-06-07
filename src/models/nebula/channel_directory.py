from pydantic import BaseModel, HttpUrl


class NebulaChannelDirectoryResult(BaseModel):
    slug: str
    title: str
    type: str | None = None
    description: str | None = None
    assets: dict | None = None
    share_url: HttpUrl | None = None
    website: HttpUrl | None = None

    def avatar_url(self) -> str | None:
        """Best-effort 128px avatar original URL; None if absent."""
        try:
            return self.assets["avatar"]["128"]["original"]
        except (KeyError, TypeError):
            return None


class NebulaChannelDirectoryResponse(BaseModel):
    next: HttpUrl | None = None
    previous: HttpUrl | None = None
    results: list[NebulaChannelDirectoryResult]
