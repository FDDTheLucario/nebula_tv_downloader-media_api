from yt_dlp import YoutubeDL
from pathlib import Path
import requests
from PIL import Image
from models.nebula.Streaming import NebulaVideoContentStreamSubtitles
from urllib.parse import urlparse


def download_video(
    url: str,
    output_file: Path,
    quiet: bool = False,
    download_format: str = "bestvideo+bestaudio/best",
    max_file_size: int | None = None,
    subtitle_languages: list[str] = ["en", "de", "ru"],  # skipcq: PYL-W0102
) -> None:
    ydl_opts = {
        "outtmpl": output_file.__str__() + ".%(ext)s",
        "format": download_format,
        "quiet": quiet,
        "embedthumbnail": True,
        "embedsubtitle": True,
        "embeddescription": True,
        "embedchapters": True,
        "subtitleslangs": subtitle_languages,
        "convertthumbnails": "jpg",
        "max_filesize": max_file_size,
    }
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return


def download_thumbnail(
    url: str,
    output_file: Path,
    max_resolution: tuple[int, int] | None = None,
    compress_image: bool = False,
) -> None:
    with open(output_file, "wb") as file:
        file.write(requests.get(url).content)
    if compress_image:
        img = Image.open(output_file)
        if max_resolution is not None:
            img.thumbnail(max_resolution, Image.Resampling.LANCZOS)
        img.save(output_file, format="JPEG", quality=85, optimize=True, progressive=True)
    return


def download_subtitles(
    subtitles: list[NebulaVideoContentStreamSubtitles],
    output_directory: Path,
) -> None:
    for subtitle in subtitles:
        output_name: str = (
            subtitle.language_code
            + "-"
            + urlparse(str(subtitle.url))
            .path.split("/")[-1]
            .replace("-", "_")
            .replace(".", "_")
            .replace("_vtt", ".vtt")
        )
        output_filename: Path = output_directory / output_name
        if output_filename.exists():
            return
        with open(output_filename, "wb") as file:
            file.write(requests.get(subtitle.url).content)
    return
