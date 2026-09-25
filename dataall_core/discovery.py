"""Discover connection settings from a deployed data.all front page."""

import re
from typing import Any, Dict, Optional, cast
from urllib.parse import urljoin, urlparse

import httpx

from dataall_core.auth.oidc_browser_auth import (
    DEFAULT_FALLBACK_REDIRECT_URI,
    DEFAULT_REDIRECT_URI,
    DEFAULT_SCOPES,
)
from dataall_core.exceptions import MissingParametersException
from dataall_core.profile import AuthType, Profile

BUNDLE_PATTERN = re.compile(r'src="([^"]*static/js/main\.[^"]+\.js)"')
VALUE_PATTERN = re.compile(r'(REACT_APP_[A-Z_]+):"([^"]*)"')
API_SUFFIX = "/graphql/api"
REQUIRED_KEYS = ("auth_type", "client_id", "idp_domain_url", "api_endpoint_url")


def frontend_origin(dataall_url: str) -> str:
    """Return ``scheme://host`` of a data.all URL."""
    parsed = urlparse(dataall_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def profile_name_for(dataall_url: str) -> str:
    """Return the profile name used for a front page URL: its host name."""
    return urlparse(dataall_url).hostname or dataall_url


def discover_from_frontend(dataall_url: str) -> Dict[str, str]:
    """Read the auth type, identity provider, client id and API endpoint from the front page bundle.

    Returns ``frontend_url`` plus whichever values were found.
    """
    found = {"frontend_url": frontend_origin(dataall_url)}
    base = found["frontend_url"] + "/"
    index = httpx.get(base, follow_redirects=True, timeout=30)
    index.raise_for_status()
    match = BUNDLE_PATTERN.search(index.text)
    if not match:
        return found
    bundle = httpx.get(urljoin(base, match.group(1)), follow_redirects=True, timeout=60)
    bundle.raise_for_status()
    values = dict(VALUE_PATTERN.findall(bundle.text))

    if values.get("REACT_APP_CUSTOM_AUTH") and values.get("REACT_APP_CUSTOM_AUTH_URL"):
        found["auth_type"] = AuthType.OidcBrowser.value
        found["idp_domain_url"] = values["REACT_APP_CUSTOM_AUTH_URL"]
        if values.get("REACT_APP_CUSTOM_AUTH_CLIENT_ID"):
            found["client_id"] = values["REACT_APP_CUSTOM_AUTH_CLIENT_ID"]
    elif values.get("REACT_APP_COGNITO_APP_CLIENT_ID"):
        found["auth_type"] = AuthType.Cognito.value
        found["client_id"] = values["REACT_APP_COGNITO_APP_CLIENT_ID"]
        domain = values.get("REACT_APP_COGNITO_DOMAIN", "")
        if domain:
            found["idp_domain_url"] = domain if "://" in domain else f"https://{domain}"
        if values.get("REACT_APP_COGNITO_REDIRECT_SIGNIN"):
            found["redirect_uri"] = values["REACT_APP_COGNITO_REDIRECT_SIGNIN"]
    api = values.get("REACT_APP_GRAPHQL_API", "")
    if api:
        found["api_endpoint_url"] = (
            api[: -len(API_SUFFIX)] if api.endswith(API_SUFFIX) else api
        )
    return found


def profile_from_frontend(
    dataall_url: str,
    profile_name: Optional[str] = None,
    creds_path: Optional[str] = None,
) -> Profile:
    """Build a Profile from the values embedded in the front page bundle.

    OIDC deployments get the loopback redirect defaults of ``OidcBrowserAuth``.
    Raises ``MissingParametersException`` naming any value that could not be read.
    """
    found = discover_from_frontend(dataall_url)
    missing = [key for key in REQUIRED_KEYS if key not in found]
    if found.get("auth_type") == AuthType.Cognito.value and "redirect_uri" not in found:
        missing.append("redirect_uri")
    if missing:
        raise MissingParametersException(
            f"Could not discover {', '.join(missing)} from {dataall_url}"
        )
    if found["auth_type"] == AuthType.OidcBrowser.value:
        found.setdefault("redirect_uri", DEFAULT_REDIRECT_URI)
        found.setdefault("fallback_redirect_uri", DEFAULT_FALLBACK_REDIRECT_URI)
        found.setdefault("scopes", DEFAULT_SCOPES)
    if creds_path:
        found["creds_path"] = creds_path
    return Profile(
        profile_name=profile_name or profile_name_for(dataall_url),
        **cast(Dict[str, Any], found),
    )
