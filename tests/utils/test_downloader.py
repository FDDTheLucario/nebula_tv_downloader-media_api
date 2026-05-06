from pathlib import Path

from models.nebula.streaming import NebulaVideoContentStreamSubtitles
from utils.downloader import download_subtitles, download_thumbnail, download_video


def test_download_video_invokes_yt_dlp_with_expected_options(mocker, tmp_path):
    mock_ydl_class = mocker.patch("utils.downloader.YoutubeDL")
    mock_instance = mock_ydl_class.return_value.__enter__.return_value

    out = tmp_path / "video"
    download_video(
        url="https://example.com/manifest.m3u8",
        output_file=out,
        quiet=True,
        download_format="best",
        max_file_size=1024,
        subtitle_languages=["en"],
    )

    args, _ = mock_ydl_class.call_args
    opts = args[0]
    assert opts["outtmpl"] == f"{out}.%(ext)s"
    assert opts["format"] == "best"
    assert opts["quiet"] is True
    assert opts["embedthumbnail"] is True
    assert opts["embedsubtitle"] is True
    assert opts["embeddescription"] is True
    assert opts["embedchapters"] is True
    assert opts["subtitleslangs"] == ["en"]
    assert opts["convertthumbnails"] == "jpg"
    assert opts["max_filesize"] == 1024
    mock_instance.download.assert_called_once_with(["https://example.com/manifest.m3u8"])


def test_download_video_default_subtitle_languages(mocker, tmp_path):
    mock_ydl_class = mocker.patch("utils.downloader.YoutubeDL")
    download_video(url="https://example.com/m", output_file=tmp_path / "v")
    opts = mock_ydl_class.call_args[0][0]
    assert opts["subtitleslangs"] == ["en", "de", "ru"]


def test_download_thumbnail_writes_response_content_to_file(mocker, tmp_path):
    response = mocker.Mock()
    response.content = b"\x89PNGdata"
    mocker.patch("utils.downloader.requests.get", return_value=response)
    mock_image = mocker.patch("utils.downloader.Image")

    out = tmp_path / "thumb.jpg"
    download_thumbnail(url="https://example.com/t.jpg", output_file=out)

    assert out.read_bytes() == b"\x89PNGdata"
    mock_image.open.assert_not_called()


def test_download_thumbnail_compresses_when_requested(mocker, tmp_path):
    response = mocker.Mock()
    response.content = b"data"
    mocker.patch("utils.downloader.requests.get", return_value=response)
    mock_image_module = mocker.patch("utils.downloader.Image")
    mock_img = mock_image_module.open.return_value

    out = tmp_path / "thumb.jpg"
    download_thumbnail(
        url="https://example.com/t.jpg",
        output_file=out,
        max_resolution=(320, 240),
        compress_image=True,
    )

    mock_image_module.open.assert_called_once_with(out)
    mock_img.thumbnail.assert_called_once_with((320, 240), mock_image_module.Resampling.LANCZOS)
    mock_img.save.assert_called_once_with(
        out, format="JPEG", quality=85, optimize=True, progressive=True
    )


def test_download_thumbnail_compress_without_resolution_skips_thumbnail(mocker, tmp_path):
    response = mocker.Mock()
    response.content = b"data"
    mocker.patch("utils.downloader.requests.get", return_value=response)
    mock_image_module = mocker.patch("utils.downloader.Image")
    mock_img = mock_image_module.open.return_value

    out = tmp_path / "thumb.jpg"
    download_thumbnail(
        url="https://example.com/t.jpg", output_file=out, compress_image=True
    )

    mock_img.thumbnail.assert_not_called()
    mock_img.save.assert_called_once()


def _subtitle(language_code: str, url: str) -> NebulaVideoContentStreamSubtitles:
    return NebulaVideoContentStreamSubtitles(
        language_code=language_code, url=url, language=language_code
    )


def test_download_subtitles_writes_files_with_language_prefixed_name(mocker, tmp_path):
    response = mocker.Mock()
    response.content = b"WEBVTT"
    mocker.patch("utils.downloader.requests.get", return_value=response)

    subs = [_subtitle("en", "https://example.com/path/foo-bar.vtt")]
    download_subtitles(subtitles=subs, output_directory=tmp_path)

    written = list(tmp_path.iterdir())
    assert len(written) == 1
    assert written[0].name.startswith("en-")
    assert written[0].name.endswith(".vtt")
    assert written[0].read_bytes() == b"WEBVTT"


def test_download_subtitles_skips_when_file_exists(mocker, tmp_path):
    mock_get = mocker.patch("utils.downloader.requests.get")
    sub = _subtitle("en", "https://example.com/path/foo.vtt")

    expected_name = "en-foo_vtt".replace("_vtt", ".vtt")
    (tmp_path / expected_name).write_bytes(b"existing")

    download_subtitles(subtitles=[sub], output_directory=tmp_path)
    mock_get.assert_not_called()
    assert (tmp_path / expected_name).read_bytes() == b"existing"


def test_download_subtitles_empty_list_is_noop(mocker, tmp_path):
    mock_get = mocker.patch("utils.downloader.requests.get")
    download_subtitles(subtitles=[], output_directory=tmp_path)
    mock_get.assert_not_called()
