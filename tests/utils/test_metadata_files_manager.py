from xml.etree import ElementTree

from models.nebula.channel import NebulaChannelVideoContentDetails
from models.nebula.episode import NebulaChannelVideoContentEpisodeResult
from utils.metadata_files_manager import create_nfo_for_channel, create_nfo_for_video
from tests.models.nebula.test_channel import _channel_payload
from tests.models.nebula.test_episode import _episode_payload


def _channel(**overrides):
    return NebulaChannelVideoContentDetails(**_channel_payload(**overrides))


def _episode(**overrides):
    return NebulaChannelVideoContentEpisodeResult(**_episode_payload(**overrides))


def test_create_nfo_for_video_writes_expected_xml_fields(tmp_path):
    episode = _episode(
        published_at="2024-03-15T12:00:00Z",
        title="Episode Title",
        description="The plot",
        id="ep-id",
        channel_title="Channel",
        slug="ep-slug",
    )
    create_nfo_for_video(episode, tmp_path)
    nfo = tmp_path / "ep-slug.nfo"
    assert nfo.is_file()

    root = ElementTree.fromstring(nfo.read_text())
    assert root.tag == "episodedetails"
    assert root.findtext("title") == "Episode Title"
    assert root.findtext("showtitle") == "Channel"
    assert root.findtext("plot") == "The plot"
    assert root.findtext("unique_id") == "ep-id"
    assert root.findtext("premiered") == "2024-03-15"
    assert root.findtext("season") == "2024"


def test_create_nfo_for_channel_writes_expected_xml_fields(tmp_path):
    channel_data = _channel(title="My Channel", description="Channel plot")
    create_nfo_for_channel(channel_data, tmp_path)
    nfo = tmp_path / "tvshow.nfo"
    assert nfo.is_file()

    root = ElementTree.fromstring(nfo.read_text())
    assert root.tag == "channeldetails"
    assert root.findtext("title") == "My Channel"
    assert root.findtext("plot") == "Channel plot"
