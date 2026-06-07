from fastapi import FastAPI

from serve import build


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
