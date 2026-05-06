from pydantic import BaseModel
from pathlib import Path


class ConfigurationNebulaAPIModel(BaseModel):
    user_api_token: str
    authorization_header: str | None = None
    user_agent: str
    token_refresh_interval_hours: int

    def __init__(self, **data):
        super().__init__(**data)
        self.authorization_header = self.authorization_header or None


class ConfigurationNebulaFiltersModel(BaseModel):
    category_search: str | None = None
    include_nebula_first: bool = True
    include_nebula_plus: bool = True
    include_nebula_originals: bool = True
    include_regular_videos: bool = False
    channels_to_parse: list[str] | None = None

    def __init__(self, **data):
        super().__init__(**data)
        self.channels_to_parse = (
            list(filter(None, self.channels_to_parse))
            if self.channels_to_parse
            else None
        )


class ConfigurationDownloaderModel(BaseModel):
    download_path: Path
    load_channel_data_from_db: bool
    skip_if_video_exists: bool

    def __init__(self, **data):
        super().__init__(**data)
        self.download_path = Path(self.download_path)


class ConfigurationModel(BaseModel):
    nebula_api: ConfigurationNebulaAPIModel
    nebula_filters: ConfigurationNebulaFiltersModel
    downloader: ConfigurationDownloaderModel
