import pytest
from pydantic import ValidationError

from models.nebula.fetched import (
    NebulaChannelVideoContentEpisodes,
    NebulaChannelVideoContentResponseModel,
)
from tests.models.nebula.test_channel import _channel_payload
from tests.models.nebula.test_episode import _episode_payload


def test_episodes_wrapper_no_pagination():
    payload = {"next": None, "previous": None, "results": []}
    eps = NebulaChannelVideoContentEpisodes(**payload)
    assert eps.next is None
    assert eps.previous is None
    assert eps.results == []


def test_episodes_wrapper_with_results_and_next():
    payload = {
        "next": "https://example.com/next",
        "previous": None,
        "results": [_episode_payload()],
    }
    eps = NebulaChannelVideoContentEpisodes(**payload)
    assert str(eps.next) == "https://example.com/next"
    assert len(eps.results) == 1


def test_episodes_wrapper_invalid_next_url_raises():
    with pytest.raises(ValidationError):
        NebulaChannelVideoContentEpisodes(next="not-a-url", previous=None, results=[])


def test_response_model_aggregates_details_and_episodes():
    response = NebulaChannelVideoContentResponseModel(
        details=_channel_payload(),
        episodes={"next": None, "previous": None, "results": [_episode_payload()]},
    )
    assert response.details.slug == "ch-slug"
    assert len(response.episodes.results) == 1
