from configparser import ConfigParser
from pathlib import Path
from models.configuration import (
    ConfigurationModel,
    ConfigurationNebulaAPIModel,
    ConfigurationNebulaFiltersModel,
    ConfigurationDownloaderModel,
)


class QuotedConfigParser(ConfigParser):
    def get(self, section, option, **kwargs):
        value = super().get(section, option, **kwargs)
        return value.strip('"').strip("'")


class Config:
    def __init__(self, config_path: Path = Path("../config/config.ini")) -> None:
        config_original = QuotedConfigParser()
        config_original.read(config_path)
        self.__CONFIG = ConfigurationModel(
            NebulaAPI=ConfigurationNebulaAPIModel(
                USER_API_TOKEN=config_original.get("NebulaAPI", "USER_API_TOKEN"),
                AUTHORIZATION_HEADER=config_original.get(
                    "NebulaAPI", "AUTHORIZATION_HEADER"
                ),
                USER_AGENT=config_original.get("NebulaAPI", "USER_AGENT")
                if config_original.get("NebulaAPI", "USER_AGENT")
                else None,
            ),
            NebulaFilters=ConfigurationNebulaFiltersModel(
                CATEGORY_SEARCH=str(
                    config_original.get("NebulaFilters", "CATEGORY_SEARCH")
                )
                if not config_original.get("NebulaFilters", "CATEGORY_SEARCH") == "false"
                else None,
                INCLUDE_NEBULA_FIRST=config_original.getboolean(
                    "NebulaFilters", "INCLUDE_NEBULA_FIRST"
                ),
                INCLUDE_NEBULA_PLUS=config_original.getboolean(
                    "NebulaFilters", "INCLUDE_NEBULA_PLUS"
                ),
                INCLUDE_NEBULA_ORIGINALS=config_original.getboolean(
                    "NebulaFilters", "INCLUDE_NEBULA_ORIGINALS"
                ),
                INCLUDE_REGULAR_VIDEOS=config_original.getboolean(
                    "NebulaFilters", "INCLUDE_REGULAR_VIDEOS"
                ),
                CHANNELS_TO_PARSE=config_original.get(
                    "NebulaFilters", "CHANNELS_TO_PARSE"
                ).split(",")
                if config_original["NebulaFilters"]["CHANNELS_TO_PARSE"]
                else None,
            ),
            Downloader=ConfigurationDownloaderModel(
                DOWNLOAD_PATH=config_original.get("Downloader", "DOWNLOAD_PATH"),
            ),
        )

    @property
    def NebulaAPI(self) -> ConfigurationNebulaAPIModel:
        return self.__CONFIG.NebulaAPI

    @property
    def NebulaFilters(self) -> ConfigurationNebulaFiltersModel:
        return self.__CONFIG.NebulaFilters

    @property
    def Downloader(self) -> ConfigurationDownloaderModel:
        return self.__CONFIG.Downloader

    def setNebulaAuthorizationToken(self, token: str) -> None:
        self.__CONFIG.NebulaAPI.AUTHORIZATION_HEADER = token
