from models.nebula.channel_directory import (
    NebulaChannelDirectoryResponse,
    NebulaChannelDirectoryResult,
)


def _avatar_assets():
    return {
        "avatar": {
            "128": {
                "original": "https://images.nebula.tv/abc.jpeg?width=128",
                "webp": "https://images.nebula.tv/abc.webp?width=128",
            }
        }
    }


def _directory_result_payload(slug="12tone", title="12tone", with_avatar=True):
    payload = {"slug": slug, "title": title, "type": "video_channel"}
    if with_avatar:
        payload["assets"] = _avatar_assets()
    return payload


def _directory_payload(*results, next_url=None):
    return {
        "next": next_url,
        "previous": None,
        "results": list(results),
    }


def test_directory_result_parses_minimal():
    r = NebulaChannelDirectoryResult(slug="x", title="X")
    assert r.slug == "x"
    assert r.title == "X"
    assert r.avatar_url() is None


def test_directory_result_avatar_url():
    r = NebulaChannelDirectoryResult(**_directory_result_payload())
    assert r.avatar_url() == "https://images.nebula.tv/abc.jpeg?width=128"


def test_directory_result_avatar_url_missing_keys():
    assert NebulaChannelDirectoryResult(slug="x", title="X", assets={}).avatar_url() is None
    assert (
        NebulaChannelDirectoryResult(slug="x", title="X", assets=None).avatar_url()
        is None
    )


def test_directory_response_parses():
    payload = _directory_payload(
        _directory_result_payload(slug="a", title="A"),
        _directory_result_payload(slug="b", title="B"),
    )
    resp = NebulaChannelDirectoryResponse(**payload)
    assert len(resp.results) == 2
    assert resp.next is None


def test_directory_response_next_url():
    payload = _directory_payload(
        _directory_result_payload(),
        next_url="https://content.api.nebula.app/video/channels/?offset=20",
    )
    resp = NebulaChannelDirectoryResponse(**payload)
    assert str(resp.next).endswith("offset=20")
