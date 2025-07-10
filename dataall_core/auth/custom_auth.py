"""Dataall Core Auth Class."""

import base64
import hashlib
import json
import logging
import secrets
import urllib.parse
from datetime import datetime, timedelta
from typing import Any, Optional, Tuple, cast

import bs4
import httpx
from bs4 import Tag

from dataall_core.auth import AuthorizationClass
from dataall_core.profile import Profile

logger = logging.getLogger(__name__)


class CustomAuth(AuthorizationClass):
    """data.all client class to handle authentication and retrieval of JWT token.

    This class either uses Cognito User Pool or 3rd Part OIDC Identity Provider (e.g. Okta) for authentication and retrieving the tokens.

    Cognito Reference: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cognito-idp/client/admin_initiate_auth.html
    """

    def __init__(self, profile: Optional[Profile] = None):
        """Initialize CustomAuth Client for a profile.

        :param profile:
        """
        super().__init__(profile)

    def _refresh_and_get_token(self) -> bool:
        """Refresh the token using the refresh token.

        :return: True if refresh was successful, False otherwise
        """
        # TODO: Test Custom Auth with valid refresh token... for now we always re-prompt for username and password
        return False

    def _authenticate_and_get_token(self, username: str, password: str) -> None:
        """Authenticate and get tokens from Custom Identity Provider.

        Authenticate using username and password in profile and retrieve JWT token
        :return: None
        """
        auth_endpoint, token_endpoint = self.get_endpoints()
        session_token = self.get_session_token(username, password)
        code, code_verifier = self.get_authorization_code(auth_endpoint, session_token)
        response = self._get_token_custom(token_endpoint, code, code_verifier)
        self.set_profile_tokens(
            response.get("access_token", None),
            datetime.now() + timedelta(seconds=response.get("expires_in")),
            response.get("refresh_token", None),
        )

    def get_endpoints(self) -> Tuple[str, str]:
        """Get the auth endpoints for the profile.

        :return: Tuple(str ,str)
        """
        if self.profile.auth_server and self.profile.auth_server != "default":
            openid_url = f"{self.profile.idp_domain_url}/oauth2/{self.profile.auth_server}/.well-known/openid-configuration"
        else:
            openid_url = (
                f"{self.profile.idp_domain_url}/.well-known/openid-configuration"
            )
        response = httpx.get(openid_url)
        openid_config = response.raise_for_status().json()

        return openid_config.get("authorization_endpoint", ""), openid_config.get(
            "token_endpoint", ""
        )

    def get_session_token(self, username: str, password: str) -> str:
        """
        Get the session token for the profile.

        :return: str
        """
        auth_params = {
            "username": username,
            "password": password,
        }

        okta_response_1 = httpx.post(
            cast(str, self.profile.session_token_endpoint),
            json=auth_params,
            # verify=False,
            # allow_redirects=True,
        )
        okta_response_1.raise_for_status()
        return cast(str, json.loads(okta_response_1.text)["sessionToken"])

    def get_authorization_code(
        self, auth_endpoint: str, session_token: str
    ) -> Tuple[str, str]:
        """
        Get the authorization code for the profile.

        :return: Tuple(str, str)
        """
        # store app state and code verifier in session
        app_state = secrets.token_urlsafe(64)
        code_verifier = secrets.token_urlsafe(64)

        # calculate code challenge
        hashed = hashlib.sha256(code_verifier.encode("ascii")).digest()
        encoded = base64.urlsafe_b64encode(hashed)
        code_challenge = encoded.decode("ascii").strip("=")

        # get request params
        query_params = {
            "client_id": self.profile.client_id,
            "redirect_uri": self.profile.redirect_uri,
            "scope": "openid email profile",
            "state": app_state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "response_type": "code",
            "response_mode": "form_post",
            "sessionToken": session_token,
        }
        request_uri = f"{auth_endpoint}?{urllib.parse.urlencode(query_params)}"
        response = httpx.get(request_uri)
        response.raise_for_status()

        page = bs4.BeautifulSoup(response.text, "html.parser")
        params = {}
        for e in page.find_all("input", {"name": True}):
            if isinstance(e, Tag) and e.get("name"):
                params[str(e["name"])] = str(e.get("value", ""))

        return str(params.get("code", "")), code_verifier

    def _get_token_custom(
        self, token_endpoint: str, code: str, code_verifier: str
    ) -> Any:
        """
        Get the token for the profile.

        :return: dict
        """
        headers = {
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded",
        }

        query_params_2 = {
            "grant_type": "authorization_code",
            "redirect_uri": self.profile.redirect_uri,
            "code": code,
            "client_id": self.profile.client_id,
            "client_secret": self.profile.client_secret,
            "code_verifier": code_verifier,
        }

        request_uri = f"{token_endpoint}?{urllib.parse.urlencode(query_params_2)}"
        response = httpx.post(request_uri, headers=headers)
        response.raise_for_status()
        return json.loads(response.text)
