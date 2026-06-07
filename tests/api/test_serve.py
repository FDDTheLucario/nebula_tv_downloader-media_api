import runpy

import pytest
from fastapi import FastAPI

from serve import build, _UnconfiguredAuth


def test_unconfigured_auth_raises_until_configured():
    auth = _UnconfiguredAuth()
    auth.refresh_authorization_token()  # no-op, must not raise
    with pytest.raises(RuntimeError):
        auth.get_authorization_header()


def test_build_without_token_starts_setup_mode(monkeypatch, config):
    """With no API token, build() starts the app without contacting Nebula."""
    config.nebula_api.user_api_token = ""
    monkeypatch.setattr("serve.Config", lambda: config)

    def fail_auth(*args, **kwargs):
        raise AssertionError("auth must not be constructed without a token")

    monkeypatch.setattr("serve.NebulaUserAuthorization", fail_auth)

    app = build()
    assert isinstance(app, FastAPI)


def test_build_creates_app(monkeypatch, config, fake_auth):
    """
    Test that build() creates a FastAPI app.

    Approach: Monkeypatch Config and NebulaUserAuthorization at the serve module
    level to avoid network calls. Also monkeypatch serve.create_app to pass
    start_background=False, ensuring no APScheduler threads or background worker
    threads are left running in the test. This keeps the test fast, deterministic,
    and leaves no live threads.
    """
    from api.app import create_app

    # Monkeypatch Config to return the test config (avoids file I/O)
    monkeypatch.setattr("serve.Config", lambda: config)

    # Monkeypatch NebulaUserAuthorization to return fake_auth (avoids network)
    monkeypatch.setattr(
        "serve.NebulaUserAuthorization",
        lambda user_token=None, authorization_header=None: fake_auth,
    )

    # Monkeypatch serve.create_app to wrap the real create_app with
    # start_background=False, preventing any background threads from starting
    def mock_create_app(cfg, auth, **kwargs):
        return create_app(cfg, auth, start_background=False)

    monkeypatch.setattr("serve.create_app", mock_create_app)

    # Call build() and verify it returns a FastAPI instance
    app = build()
    assert isinstance(app, FastAPI)

    # Verify the app has the expected routes
    routes = [route.path for route in app.routes]
    assert "/healthz" in routes
    assert "/api/status" in routes
    assert "/api/channels" in routes


def test_main_runs_uvicorn(mocker):
    """main() passes the built app to uvicorn.run."""
    import serve

    mock_app = mocker.MagicMock()
    mocker.patch("serve.build", return_value=mock_app)
    mock_run = mocker.patch("uvicorn.run")

    serve.main(host="127.0.0.1", port=9999)

    mock_run.assert_called_once_with(mock_app, host="127.0.0.1", port=9999)


def test_main_entry_point(mocker):
    """Executing serve as __main__ invokes main() which calls uvicorn.run."""
    mocker.patch("config.config.Config")
    mocker.patch("nebula_api.authorization.NebulaUserAuthorization")
    mocker.patch("api.app.create_app")
    mock_run = mocker.patch("uvicorn.run")

    runpy.run_module("serve", run_name="__main__")

    mock_run.assert_called_once()
