import socket
import threading
import urllib.request
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from dataall_core.auth import oidc_browser_auth
from dataall_core.auth.oidc_browser_auth import (
    DEVICE_GRANT,
    OidcBrowserAuth,
    new_pkce,
    openid_configuration_url,
    use_device_flow,
)
from dataall_core.exceptions import AuthenticationException
from dataall_core.profile import AuthType, Profile, ProfileCreds

ISSUER = "https://idp.example.com/oauth2/aus123"
TOKEN = {"access_token": "access-1", "expires_in": 3600, "refresh_token": "refresh-1"}
DEVICE = {
    "device_code": "dev-1",
    "user_code": "ABCD-EFGH",
    "verification_uri": "https://idp.example.com/activate",
    "verification_uri_complete": "https://idp.example.com/activate?user_code=ABCD-EFGH",
    "interval": 0,
    "expires_in": 60,
}


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def listen_on(port):
    sock = socket.socket()
    sock.bind(("127.0.0.1", port))
    sock.listen()
    return sock


def form(route, index=-1):
    return parse_qs(route.calls[index].request.content.decode())


def expired(refresh_token):
    return ProfileCreds(
        token="old",
        expires_at=(datetime.now() - timedelta(minutes=1)).isoformat(),
        refresh_token=refresh_token,
    )


@pytest.fixture(autouse=True)
def quiet_env(monkeypatch):
    monkeypatch.delenv("DATAALL_DEVICE_LOGIN", raising=False)
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.setattr(oidc_browser_auth, "_sleep", lambda seconds: None)


@pytest.fixture
def profile(tmp_path):
    return Profile(
        profile_name="OidcDefault",
        auth_type=AuthType.OidcBrowser.value,
        api_endpoint_url="https://da-api-endpoint.com/tst",
        client_id="client_id",
        redirect_uri=f"http://127.0.0.1:{free_port()}/callback",
        idp_domain_url=ISSUER,
        creds_path=str(tmp_path / "credentials.yaml"),
    )


@pytest.fixture
def idp():
    with respx.mock(base_url=ISSUER, assert_all_called=False) as mock:
        mock.get("/.well-known/openid-configuration", name="discovery").mock(
            return_value=httpx.Response(
                200,
                json={
                    "authorization_endpoint": f"{ISSUER}/v1/authorize",
                    "token_endpoint": f"{ISSUER}/v1/token",
                    "device_authorization_endpoint": f"{ISSUER}/v1/device/authorize",
                },
            )
        )
        mock.post("/v1/token", name="token").mock(
            return_value=httpx.Response(200, json=TOKEN)
        )
        mock.post("/v1/device/authorize", name="device").mock(
            return_value=httpx.Response(200, json=DEVICE)
        )
        yield mock


def browser_visits_callback(monkeypatch, redirect_uri, *queries):
    """Make webbrowser.open behave like a browser that answers each login attempt in turn."""
    seen = {"urls": []}
    pending = list(queries)

    def fake_open(url, new=0):
        seen["url"] = url
        seen["urls"].append(url)
        query = pending.pop(0) if len(pending) > 1 else pending[0]
        state = parse_qs(urlparse(url).query)["state"][0]
        target = f"{redirect_uri}?{query.format(state=state)}"
        threading.Thread(
            target=urllib.request.urlopen, args=(target,), daemon=True
        ).start()
        return True

    monkeypatch.setattr(oidc_browser_auth.webbrowser, "open", fake_open)
    return seen


def no_browser(monkeypatch):
    monkeypatch.setattr(
        oidc_browser_auth.webbrowser,
        "open",
        lambda *a, **k: pytest.fail("browser opened"),
    )


def test_cached_token_skips_network(profile, idp):
    profile.credentials = ProfileCreds(
        token="cached", expires_at=(datetime.now() + timedelta(hours=1)).isoformat()
    )
    assert OidcBrowserAuth(profile).get_jwt_token() == "cached"
    assert not idp["discovery"].called


def test_browser_login(profile, idp, monkeypatch, capsys):
    seen = browser_visits_callback(
        monkeypatch, profile.redirect_uri, "code=CODE1&state={state}"
    )

    assert OidcBrowserAuth(profile).get_jwt_token() == "access-1"

    query = parse_qs(urlparse(seen["url"]).query)
    assert seen["url"].startswith(f"{ISSUER}/v1/authorize?")
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["openid offline_access"]
    assert query["redirect_uri"] == [profile.redirect_uri]
    body = form(idp["token"])
    assert body["grant_type"] == ["authorization_code"]
    assert body["code"] == ["CODE1"]
    assert body["client_id"] == ["client_id"]
    assert body["redirect_uri"] == [profile.redirect_uri]
    assert "code_verifier" in body
    assert "client_secret" not in body
    assert profile.credentials.refresh_token == "refresh-1"
    assert profile.credentials.expires_at
    assert "v1/authorize?" in capsys.readouterr().err


def test_browser_login_uses_fallback_port(profile, idp, monkeypatch):
    busy = listen_on(urlparse(profile.redirect_uri).port)
    profile.fallback_redirect_uri = f"http://127.0.0.1:{free_port()}/callback"
    browser_visits_callback(
        monkeypatch, profile.fallback_redirect_uri, "code=CODE1&state={state}"
    )
    try:
        OidcBrowserAuth(profile).get_jwt_token()
    finally:
        busy.close()
    assert form(idp["token"])["redirect_uri"] == [profile.fallback_redirect_uri]


def test_all_ports_busy_falls_back_to_device_flow(profile, idp, monkeypatch):
    busy = listen_on(urlparse(profile.redirect_uri).port)
    no_browser(monkeypatch)
    try:
        assert OidcBrowserAuth(profile).get_jwt_token() == "access-1"
    finally:
        busy.close()
    assert idp["device"].called
    assert form(idp["token"])["grant_type"] == [DEVICE_GRANT]


def test_non_loopback_redirect_uses_device_flow(profile, idp, monkeypatch):
    profile.redirect_uri = "https://dataall.example.com/callback"
    no_browser(monkeypatch)
    assert OidcBrowserAuth(profile).get_jwt_token() == "access-1"
    assert idp["device"].called


def test_browser_unavailable_falls_back_to_device_flow(
    profile, idp, monkeypatch, capsys
):
    monkeypatch.setattr(oidc_browser_auth.webbrowser, "open", lambda *a, **k: False)
    assert OidcBrowserAuth(profile).get_jwt_token() == "access-1"
    assert idp["device"].called
    assert "ABCD-EFGH" in capsys.readouterr().err


def test_state_mismatch(profile, idp, monkeypatch):
    browser_visits_callback(monkeypatch, profile.redirect_uri, "code=CODE1&state=wrong")
    with pytest.raises(AuthenticationException, match="State mismatch"):
        OidcBrowserAuth(profile).get_jwt_token()
    assert not idp["token"].called


def test_error_callback(profile, idp, monkeypatch):
    seen = browser_visits_callback(
        monkeypatch,
        profile.redirect_uri,
        "error=access_denied&error_description=User+denied&state={state}",
    )
    with pytest.raises(AuthenticationException, match="access_denied: User denied"):
        OidcBrowserAuth(profile).get_jwt_token()
    assert not idp["token"].called
    assert [parse_qs(urlparse(u).query)["scope"] for u in seen["urls"]] == [
        ["openid offline_access"],
        ["openid"],
    ]


def test_browser_login_retries_with_openid_after_policy_denial(
    profile, idp, monkeypatch
):
    seen = browser_visits_callback(
        monkeypatch,
        profile.redirect_uri,
        "error=access_denied&error_description=Policy+evaluation+failed&state={state}",
        "code=CODE1&state={state}",
    )
    assert OidcBrowserAuth(profile).get_jwt_token() == "access-1"
    assert [parse_qs(urlparse(u).query)["scope"] for u in seen["urls"]] == [
        ["openid offline_access"],
        ["openid"],
    ]
    assert form(idp["token"])["code"] == ["CODE1"]


def test_state_mismatch_is_not_retried(profile, idp, monkeypatch):
    seen = browser_visits_callback(
        monkeypatch, profile.redirect_uri, "code=CODE1&state=wrong"
    )
    with pytest.raises(AuthenticationException, match="State mismatch"):
        OidcBrowserAuth(profile).get_jwt_token()
    assert len(seen["urls"]) == 1


def test_callback_timeout(profile, idp, monkeypatch):
    monkeypatch.setattr(oidc_browser_auth, "LOGIN_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(oidc_browser_auth.webbrowser, "open", lambda *a, **k: True)
    with pytest.raises(AuthenticationException, match="Timed out"):
        OidcBrowserAuth(profile).get_jwt_token()


def test_device_login_polls_until_authorized(profile, idp, monkeypatch, capsys):
    monkeypatch.setenv("DATAALL_DEVICE_LOGIN", "1")
    sleeps = []
    monkeypatch.setattr(oidc_browser_auth, "_sleep", sleeps.append)
    replies = iter(
        [
            httpx.Response(400, json={"error": "authorization_pending"}),
            httpx.Response(400, json={"error": "slow_down"}),
            httpx.Response(200, json=TOKEN),
        ]
    )
    idp["token"].mock(side_effect=lambda request: next(replies))

    assert OidcBrowserAuth(profile).get_jwt_token() == "access-1"

    assert idp["token"].call_count == 3
    assert sleeps == [0, 0, 5]
    body = form(idp["token"])
    assert body["grant_type"] == [DEVICE_GRANT]
    assert body["device_code"] == ["dev-1"]
    assert form(idp["device"])["scope"] == ["openid offline_access"]
    assert "ABCD-EFGH" in capsys.readouterr().err


@pytest.mark.parametrize("error", ["access_denied", "expired_token"])
def test_device_login_stops_on_error(profile, idp, monkeypatch, error):
    monkeypatch.setenv("DATAALL_DEVICE_LOGIN", "1")
    idp["token"].mock(return_value=httpx.Response(400, json={"error": error}))
    with pytest.raises(AuthenticationException, match=error):
        OidcBrowserAuth(profile).get_jwt_token()


def test_device_login_requires_endpoint(profile, idp, monkeypatch):
    monkeypatch.setenv("DATAALL_DEVICE_LOGIN", "1")
    idp["discovery"].mock(
        return_value=httpx.Response(
            200,
            json={
                "authorization_endpoint": f"{ISSUER}/v1/authorize",
                "token_endpoint": f"{ISSUER}/v1/token",
            },
        )
    )
    with pytest.raises(AuthenticationException, match="device code flow"):
        OidcBrowserAuth(profile).get_jwt_token()


def test_refresh_token_used_before_login(profile, idp, monkeypatch):
    profile.credentials = expired("refresh-0")
    idp["token"].mock(
        return_value=httpx.Response(
            200, json={"access_token": "access-2", "expires_in": 3600}
        )
    )
    no_browser(monkeypatch)

    assert OidcBrowserAuth(profile).get_jwt_token() == "access-2"

    body = form(idp["token"])
    assert body["grant_type"] == ["refresh_token"]
    assert body["refresh_token"] == ["refresh-0"]
    assert profile.credentials.refresh_token == "refresh-0"


def test_refresh_failure_falls_back_to_login(profile, idp, monkeypatch):
    monkeypatch.setenv("DATAALL_DEVICE_LOGIN", "1")
    profile.credentials = expired("stale")
    replies = iter(
        [
            httpx.Response(400, json={"error": "invalid_grant"}),
            httpx.Response(200, json=TOKEN),
        ]
    )
    idp["token"].mock(side_effect=lambda request: next(replies))

    assert OidcBrowserAuth(profile).get_jwt_token() == "access-1"

    assert idp["token"].call_count == 2
    assert form(idp["token"], 0)["grant_type"] == ["refresh_token"]
    assert form(idp["token"], 1)["grant_type"] == [DEVICE_GRANT]


def test_invalid_scope_retries_with_openid(profile, idp, monkeypatch):
    monkeypatch.setenv("DATAALL_DEVICE_LOGIN", "1")
    replies = iter(
        [
            httpx.Response(400, json={"error": "invalid_scope"}),
            httpx.Response(200, json=DEVICE),
        ]
    )
    idp["device"].mock(side_effect=lambda request: next(replies))

    assert OidcBrowserAuth(profile).get_jwt_token() == "access-1"

    assert [form(idp["device"], i)["scope"] for i in range(2)] == [
        ["openid offline_access"],
        ["openid"],
    ]


def test_other_errors_are_not_retried(profile, idp, monkeypatch):
    monkeypatch.setenv("DATAALL_DEVICE_LOGIN", "1")
    idp["device"].mock(
        return_value=httpx.Response(401, json={"error": "invalid_client"})
    )
    with pytest.raises(AuthenticationException, match="invalid_client"):
        OidcBrowserAuth(profile).get_jwt_token()
    assert idp["device"].call_count == 1


def test_profile_scopes_and_client_secret_are_sent(profile, idp, monkeypatch):
    monkeypatch.setenv("DATAALL_DEVICE_LOGIN", "1")
    profile.scopes = "openid groups"
    profile.client_secret = "s3cret"
    OidcBrowserAuth(profile).get_jwt_token()
    assert form(idp["device"])["scope"] == ["openid groups"]
    assert form(idp["token"])["client_secret"] == ["s3cret"]


@pytest.mark.parametrize(
    "env,expected",
    [
        ({}, False),
        ({"DATAALL_DEVICE_LOGIN": "1"}, True),
        ({"SSH_CONNECTION": "10.0.0.1 1 10.0.0.2 22"}, True),
        ({"SSH_CONNECTION": "10.0.0.1 1 10.0.0.2 22", "DISPLAY": ":0"}, False),
    ],
)
def test_use_device_flow(monkeypatch, env, expected):
    monkeypatch.delenv("DISPLAY", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert use_device_flow() is expected


@pytest.mark.parametrize(
    "idp_domain_url,auth_server,expected",
    [
        (
            "https://idp/oauth2/aus1",
            "default",
            "https://idp/oauth2/aus1/.well-known/openid-configuration",
        ),
        (
            "https://idp/oauth2/aus1/",
            None,
            "https://idp/oauth2/aus1/.well-known/openid-configuration",
        ),
        (
            "https://idp",
            "aus1",
            "https://idp/oauth2/aus1/.well-known/openid-configuration",
        ),
    ],
)
def test_openid_configuration_url(idp_domain_url, auth_server, expected):
    assert openid_configuration_url(idp_domain_url, auth_server) == expected


def test_new_pkce():
    verifier, challenge = new_pkce()
    assert len(verifier) == 43
    assert "=" not in verifier + challenge
    assert challenge != verifier
