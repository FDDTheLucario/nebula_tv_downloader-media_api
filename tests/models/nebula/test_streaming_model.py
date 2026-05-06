import pytest
from pydantic import ValidationError

from models.nebula.streaming import (
    NebulaVideoContentStreamingResponseModel,
    NebulaVideoContentStreamSubtitles,
)


def _subtitle_payload():
    return {
        "language_code": "en",
        "url": "https://example.com/sub.vtt",
        "language": "English",
    }


def test_subtitle_model_parses():
    sub = NebulaVideoContentStreamSubtitles(**_subtitle_payload())
    assert sub.language_code == "en"
    assert str(sub.url) == "https://example.com/sub.vtt"
    assert sub.language == "English"


def test_subtitle_model_invalid_url_raises():
    payload = _subtitle_payload()
    payload["url"] = "not-a-url"
    with pytest.raises(ValidationError):
        NebulaVideoContentStreamSubtitles(**payload)


def test_streaming_response_model_parses_minimal():
    payload = {
        "manifest": "https://example.com/manifest.m3u8",
        "download": "https://example.com/file.mp4",
        "iframe": None,
        "bif": {},
        "subtitles": [_subtitle_payload()],
    }
    model = NebulaVideoContentStreamingResponseModel(**payload)
    assert str(model.manifest) == "https://example.com/manifest.m3u8"
    assert len(model.subtitles) == 1
    assert model.iframe is None


def test_streaming_response_model_download_optional_string():
    payload = {
        "manifest": "https://example.com/manifest.m3u8",
        "download": "expired",
        "bif": {},
        "subtitles": [],
    }
    model = NebulaVideoContentStreamingResponseModel(**payload)
    assert model.download == "expired"


def test_streaming_response_model_missing_manifest_raises():
    with pytest.raises(ValidationError):
        NebulaVideoContentStreamingResponseModel(bif={}, subtitles=[])
