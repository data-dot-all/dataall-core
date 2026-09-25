"""OIDC login through the system browser (Authorization Code + PKCE) or the device code flow."""

import base64
import hashlib
import hmac
import logging
import os
import secrets
import socket
import sys
import time
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional, Tuple, cast
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from dataall_core.auth import AuthorizationClass
from dataall_core.exceptions import AuthenticationException
from dataall_core.profile import Profile

logger = logging.getLogger(__name__)

DEFAULT_REDIRECT_URI = "http://localhost:8765/callback"
DEFAULT_FALLBACK_REDIRECT_URI = "http://localhost:8766/callback"
DEFAULT_SCOPES = "openid offline_access"
SCOPE_RETRY_ERRORS = ("invalid_scope", "access_denied")
LOGIN_TIMEOUT_SECONDS = 300
EXPIRY_LEEWAY_SECONDS = 60
DEVICE_LOGIN_ENV = "DATAALL_DEVICE_LOGIN"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

_sleep = time.sleep


def openid_configuration_url(idp_domain_url: str, auth_server: Optional[str]) -> str:
    """Build the OpenID discovery URL, honouring the Okta ``auth_server`` convention."""
    base = idp_domain_url.rstrip("/")
    if auth_server and auth_server != "default":
        base = f"{base}/oauth2/{auth_server}"
    return f"{base}/.well-known/openid-configuration"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def new_pkce() -> Tuple[str, str]:
    """Return a PKCE ``(code_verifier, code_challenge)`` pair using S256."""
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def new_state() -> str:
    """Return a random OAuth ``state`` value."""
    return secrets.token_urlsafe(24)


def is_loopback(redirect_uri: str) -> bool:
    """Return True when the redirect URI points at this machine."""
    return urlparse(redirect_uri).hostname in LOOPBACK_HOSTS


def use_device_flow() -> bool:
    """Return True when the device code flow is requested or no browser can open here."""
    if os.environ.get(DEVICE_LOGIN_ENV):
        return True
    return bool(os.environ.get("SSH_CONNECTION")) and not os.environ.get("DISPLAY")


class _CallbackServer(HTTPServer):
    def __init__(
        self, address: Tuple[str, int], callback_path: str, redirect_uri: str
    ) -> None:
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        self.callback_path = callback_path
        self.redirect_uri = redirect_uri
        self.params: Optional[Dict[str, str]] = None
        super().__init__(address, _CallbackHandler)


class _CallbackHandler(BaseHTTPRequestHandler):
    timeout = 10

    def do_GET(self) -> None:
        server = cast(_CallbackServer, self.server)
        parsed = urlparse(self.path)
        if parsed.path != server.callback_path:
            self.send_error(404)
            return
        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        server.params = params
        if "code" in params:
            body = "data.all CLI login complete. You can close this tab."
        else:
            body = f"Login failed: {params.get('error_description') or params.get('error') or 'no code'}"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug(fmt, *args)


class OidcBrowserAuth(AuthorizationClass):
    """Authenticate against an OIDC provider without a password.

    Default: open the system browser, receive the authorization code on a loopback
    redirect URI and exchange it with PKCE. Without a usable browser (SSH session or
    ``DATAALL_DEVICE_LOGIN=1``) the device code flow is used instead. Tokens are renewed
    with the refresh token when the provider issues one (``offline_access`` scope).
    """

    def __init__(self, profile: Optional[Profile] = None):
        """Initialize OidcBrowserAuth for a profile.

        :param profile:
        """
        super().__init__(profile)

    def _authenticate_interactive(self) -> None:
        self.login()

    def _authenticate_and_get_token(self, username: str, password: str) -> None:
        self.login()

    def _refresh_and_get_token(self) -> bool:
        refresh_token = cast(str, self.profile.credentials.refresh_token)
        try:
            config = self.get_endpoints()
            token = self._post_token(
                config["token_endpoint"],
                {"grant_type": "refresh_token", "refresh_token": refresh_token},
            )
        except (httpx.HTTPError, AuthenticationException, KeyError) as e:
            logger.info(f"Failed to refresh token: {e}")
            return False
        self._save_tokens(token, refresh_token)
        return True

    def get_endpoints(self) -> Dict[str, Any]:
        """Fetch the provider's OpenID configuration."""
        url = openid_configuration_url(
            self.profile.idp_domain_url, self.profile.auth_server
        )
        response = httpx.get(url, timeout=30)
        response.raise_for_status()
        return cast(Dict[str, Any], response.json())

    def login(self) -> None:
        """Run the interactive login and store the resulting tokens."""
        config = self.get_endpoints()
        scopes = self.profile.scopes or DEFAULT_SCOPES
        try:
            token = self._login_with_scopes(config, scopes)
        except AuthenticationException as e:
            if scopes == "openid" or not str(e).startswith(SCOPE_RETRY_ERRORS):
                raise
            logger.info(
                f"Login with scopes '{scopes}' failed ({e}); retrying with openid only"
            )
            token = self._login_with_scopes(config, "openid")
        self._save_tokens(token, None)

    def _login_with_scopes(self, config: Dict[str, Any], scopes: str) -> Dict[str, Any]:
        if use_device_flow():
            return self._device_login(config, scopes)
        server = self._start_loopback_server()
        if server is None:
            return self._device_login(config, scopes)
        return self._browser_login(config, scopes, server)

    def _browser_login(
        self, config: Dict[str, Any], scopes: str, server: _CallbackServer
    ) -> Dict[str, Any]:
        verifier, challenge = new_pkce()
        state = new_state()
        url = self._authorize_url(
            config, server.redirect_uri, scopes, (state, challenge)
        )
        try:
            if not self._open_browser(url):
                return self._device_login(config, scopes)
            print(
                f"Complete the sign-in in your browser. If it did not open, visit:\n{url}\n",
                file=sys.stderr,
            )
            params = self._wait_for_callback(server)
        finally:
            server.server_close()
        if "error" in params:
            raise AuthenticationException(
                f"{params['error']}: {params.get('error_description', '')}".rstrip(": ")
            )
        if not hmac.compare_digest(params.get("state", ""), state):
            raise AuthenticationException("State mismatch in login callback")
        if not params.get("code"):
            raise AuthenticationException(
                "Login callback did not include an authorization code"
            )
        return self._post_token(
            config["token_endpoint"],
            {
                "grant_type": "authorization_code",
                "redirect_uri": server.redirect_uri,
                "code": params["code"],
                "code_verifier": verifier,
            },
        )

    def _authorize_url(
        self,
        config: Dict[str, Any],
        redirect_uri: str,
        scopes: str,
        pkce: Tuple[str, str],
    ) -> str:
        state, challenge = pkce
        query = urlencode(
            {
                "client_id": self.profile.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": scopes,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{config['authorization_endpoint']}?{query}"

    def _redirect_uris(self) -> List[str]:
        uris = [self.profile.redirect_uri or DEFAULT_REDIRECT_URI]
        if self.profile.fallback_redirect_uri:
            uris.append(self.profile.fallback_redirect_uri)
        return uris

    def _start_loopback_server(self) -> Optional[_CallbackServer]:
        for uri in self._redirect_uris():
            parsed = urlparse(uri)
            if not is_loopback(uri):
                logger.warning(
                    f"redirect_uri {uri} is not a loopback address; skipping"
                )
                continue
            host = (
                "127.0.0.1"
                if parsed.hostname == "localhost"
                else cast(str, parsed.hostname)
            )
            try:
                return _CallbackServer(
                    (host, parsed.port or 80), parsed.path or "/", uri
                )
            except OSError as e:
                logger.warning(f"Cannot listen on {uri}: {e}")
        return None

    @staticmethod
    def _open_browser(url: str) -> bool:
        try:
            return webbrowser.open(url, new=2)
        except webbrowser.Error:
            return False

    @staticmethod
    def _wait_for_callback(server: _CallbackServer) -> Dict[str, str]:
        server.timeout = 1
        deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS
        while server.params is None:
            if time.monotonic() > deadline:
                raise AuthenticationException("Timed out waiting for the browser login")
            server.handle_request()
        return server.params

    def _device_login(self, config: Dict[str, Any], scopes: str) -> Dict[str, Any]:
        endpoint = config.get("device_authorization_endpoint")
        if not endpoint:
            raise AuthenticationException(
                "No browser is available and the provider does not support the device code flow"
            )
        device = self._post_token(endpoint, {"scope": scopes})
        verification_uri = (
            device.get("verification_uri_complete") or device["verification_uri"]
        )
        print(
            f"Open {verification_uri} in any browser and enter code {device['user_code']} to sign in.",
            file=sys.stderr,
        )
        interval = int(device.get("interval", 5))
        deadline = time.monotonic() + int(
            device.get("expires_in", LOGIN_TIMEOUT_SECONDS)
        )
        while time.monotonic() < deadline:
            _sleep(interval)
            response = self._post(
                config["token_endpoint"],
                {"grant_type": DEVICE_GRANT, "device_code": device["device_code"]},
            )
            if response.is_success:
                return cast(Dict[str, Any], response.json())
            error = self._error_code(response)
            if error == "slow_down":
                interval += 5
            elif error != "authorization_pending":
                raise AuthenticationException(self._error_text(response))
        raise AuthenticationException("Timed out waiting for the device code login")

    def _post(self, url: str, data: Dict[str, str]) -> httpx.Response:
        payload = {"client_id": self.profile.client_id, **data}
        if self.profile.client_secret:
            payload["client_secret"] = self.profile.client_secret
        return httpx.post(
            url, data=payload, headers={"accept": "application/json"}, timeout=30
        )

    def _post_token(self, url: str, data: Dict[str, str]) -> Dict[str, Any]:
        response = self._post(url, data)
        if response.is_error:
            raise AuthenticationException(self._error_text(response))
        return cast(Dict[str, Any], response.json())

    @staticmethod
    def _error_code(response: httpx.Response) -> str:
        try:
            return str(response.json().get("error", ""))
        except ValueError:
            return ""

    @staticmethod
    def _error_text(response: httpx.Response) -> str:
        try:
            body = response.json()
            text = f"{body.get('error', response.status_code)}: {body.get('error_description', '')}"
            return text.rstrip(": ")
        except ValueError:
            return f"HTTP {response.status_code}: {response.text[:200]}"

    def _save_tokens(
        self, token: Dict[str, Any], fallback_refresh_token: Optional[str]
    ) -> None:
        expires_in = max(int(token.get("expires_in", 3600)) - EXPIRY_LEEWAY_SECONDS, 0)
        self.set_profile_tokens(
            token["access_token"],
            datetime.now() + timedelta(seconds=expires_in),
            token.get("refresh_token") or fallback_refresh_token,
        )
