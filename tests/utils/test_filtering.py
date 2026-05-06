from models.configuration import ConfigurationNebulaFiltersModel
from models.nebula.episode import NebulaChannelVideoContentEpisodeResult
from models.nebula.video_attributes import VideoNebulaAttributes
from utils.filtering import filter_out_episodes
from tests.models.nebula.test_episode import _episode_payload


def _make_episode(attributes):
    return NebulaChannelVideoContentEpisodeResult(**_episode_payload(attributes=attributes))


def _filters(**overrides) -> ConfigurationNebulaFiltersModel:
    base = dict(
        include_nebula_first=False,
        include_nebula_plus=False,
        include_nebula_originals=False,
        include_regular_videos=False,
    )
    base.update(overrides)
    return ConfigurationNebulaFiltersModel(**base)


def test_filter_yields_only_originals_when_only_originals_enabled():
    episodes = [
        _make_episode(["is_nebula_original"]),
        _make_episode(["is_nebula_plus"]),
        _make_episode([]),
    ]
    result = list(filter_out_episodes(_filters(include_nebula_originals=True), episodes))
    assert len(result) == 1
    assert VideoNebulaAttributes.IS_NEBULA_ORIGINAL in result[0].attributes


def test_filter_yields_plus_and_first_when_both_enabled():
    episodes = [
        _make_episode(["is_nebula_plus"]),
        _make_episode(["is_nebula_first"]),
        _make_episode(["is_nebula_original"]),
        _make_episode([]),
    ]
    result = list(
        filter_out_episodes(
            _filters(include_nebula_plus=True, include_nebula_first=True),
            episodes,
        )
    )
    assert len(result) == 2


def test_filter_regular_videos_yields_episodes_with_no_attributes():
    episodes = [
        _make_episode([]),
        _make_episode(["is_nebula_plus"]),
    ]
    result = list(filter_out_episodes(_filters(include_regular_videos=True), episodes))
    assert len(result) == 1
    assert result[0].attributes == []


def test_filter_regular_videos_yields_free_sample_only_episodes():
    episodes = [
        _make_episode(["free_sample_eligible"]),
        _make_episode(["is_nebula_plus", "free_sample_eligible"]),
    ]
    result = list(filter_out_episodes(_filters(include_regular_videos=True), episodes))
    assert len(result) == 1
    assert result[0].attributes == [VideoNebulaAttributes.FREE_SAMPLE_ELIGIBLE]


def test_filter_no_filters_enabled_yields_nothing():
    episodes = [
        _make_episode(["is_nebula_plus"]),
        _make_episode([]),
    ]
    assert list(filter_out_episodes(_filters(), episodes)) == []


def test_filter_all_filters_enabled_yields_everything_except_excluded():
    episodes = [
        _make_episode(["is_nebula_plus"]),
        _make_episode(["is_nebula_first"]),
        _make_episode(["is_nebula_original"]),
        _make_episode(["free_sample_eligible"]),
        _make_episode([]),
    ]
    result = list(
        filter_out_episodes(
            _filters(
                include_nebula_plus=True,
                include_nebula_first=True,
                include_nebula_originals=True,
                include_regular_videos=True,
            ),
            episodes,
        )
    )
    assert len(result) == 5


def test_filter_empty_episode_list_yields_nothing():
    result = list(filter_out_episodes(_filters(include_nebula_plus=True), []))
    assert result == []
