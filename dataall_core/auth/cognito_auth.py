"""Dataall Core Auth Class."""

import logging
import os.path
import uuid
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests
from oauthlib.oauth2 import WebApplicationClient
from requests_oauthlib import OAuth2Session

from dataall_core.auth import AuthorizationClass
from dataall_core.profile import Profile

logger = logging.getLogger(__name__)


class CognitoAuth(AuthorizationClass):
    """data.all client class to handle authentication and retrieval of JWT token.

    This class either uses Cognito User Pool or 3rd Part OIDC Identity Provider (e.g. Okta) for authentication and retrieving the tokens.

    Cognito Reference: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cognito-idp/client/admin_initiate_auth.html
    """

    def __init__(self, profile: Optional[Profile] = None):
        """Initialize CognitoAuth Client for a profile.

        :param profile:
        """
        super().__init__(profile)

    def _refresh_and_get_token(self) -> bool:
        """Refresh the token using the refresh token.

        :return: True if refresh was successful, False otherwise
        """
        logger.info("Attempting to authenticate using refresh token")
        token_url = os.path.join(self.profile.idp_domain_url, "oauth2", "token")
        headers = {
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded",
        }
        params = {
            "grant_type": "refresh_token",
            "client_id": self.profile.client_id,
            "refresh_token": self.profile.credentials.refresh_token,
            "redirect_uri": self.profile.redirect_uri,
        }

        try:
            r = requests.post(
                token_url, params=params, headers=headers, allow_redirects=False
            )
            r.raise_for_status()
            token = r.json()
            self.set_profile_tokens(
                token.get("access_token", ""),
                datetime.now() + timedelta(seconds=token.get("expires_in")),
                self.profile.credentials.refresh_token,
            )
        except Exception as e:
            logger.info(f"Failed to refresh token: {e}")
            return False
        return True

    def _authenticate_and_get_token(self, username: str, password: str) -> None:
        """Authenticate and get tokens from Cognito.

        Authenticate following OAuth2.0 Authorization Code Flow and retrieve tokens
        :param username: Data.all username
        :param password: Data.all user password
        :return: None
        """
        token = uuid.uuid4()
        scope = "aws.cognito.signin.user.admin openid"
        token_url = os.path.join(self.profile.idp_domain_url, "oauth2", "token")
        login_url = os.path.join(self.profile.idp_domain_url, "login")

        data = {
            "_csrf": token,
            "username": username,
            "password": password,
        }
        params = {
            "client_id": self.profile.client_id,
            "scope": scope,
            "redirect_uri": self.profile.redirect_uri,
            "response_type": "code",
        }

        headers = {"cookie": f'XSRF-TOKEN={token}; csrf-state=""; csrf-state-legacy=""'}
        r = requests.post(
            login_url,
            params=params,
            data=data,
            headers=headers,
            allow_redirects=False,
        )
        r.raise_for_status()
        code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]

        client = WebApplicationClient(client_id=self.profile.client_id)
        oauth = OAuth2Session(client=client, redirect_uri=self.profile.redirect_uri)
        token = oauth.fetch_token(
            token_url=token_url,
            client_secret=self.profile.client_secret,
            client_id=self.profile.client_id,
            code=code,
            include_client_id=True,
        )
        self.set_profile_tokens(
            token.get("access_token", ""),
            datetime.fromtimestamp(token.get("expires_at", "")),
            token.get("refresh_token", ""),
        )
