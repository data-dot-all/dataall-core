"""Dataall Core Auth Class."""

import getpass
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, cast

from dataall_core.profile import ConfigType, Profile

logger = logging.getLogger(__name__)


class AuthorizationClass(ABC):
    """data.all client class to handle authentication and retrieval of JWT token.

    This class either uses Cognito User Pool or 3rd Part OIDC Identity Provider (e.g. Okta) for authentication and retrieving the tokens.

    Cognito Reference: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cognito-idp/client/admin_initiate_auth.html
    """

    profile: Profile

    def __init__(self, profile: Optional[Profile] = None):
        """Initialize Client for a profile.

        :param profile:
        """
        self.profile = cast(Profile, profile)

    def get_jwt_token(self) -> str:
        """Retrieve save token from config file and if expired generate new token using the refresh token.

        :return: JWT token
        """
        if (
            self.profile.credentials.token is None
            or self.profile.credentials.expires_at is None
            or datetime.now()
            > datetime.fromisoformat(self.profile.credentials.expires_at)
        ):
            refresh_successful = False
            if self.profile.credentials.refresh_token:
                refresh_successful = self._refresh_and_get_token()

            if not refresh_successful:
                logger.info("Failed to refresh token. Authenticating...")
                username = self.profile.username
                password = self.profile.password
                if not username or self.profile.config_type == ConfigType.LOCAL.value:
                    username = input("Provide your data.all username: ")
                if not password or self.profile.config_type == ConfigType.LOCAL.value:
                    password = getpass.getpass(
                        prompt="Provide your data.all password: "
                    )
                self._authenticate_and_get_token(username, password)
        return cast(str, self.profile.credentials.token)

    @abstractmethod
    def _refresh_and_get_token(self) -> bool:
        """Refresh the token using the refresh token.

        :return: True if refresh was successful, False otherwise
        """
        ...

    @abstractmethod
    def _authenticate_and_get_token(self, username: str, password: str) -> None:
        """Handle the authentication adn token retrieval.

         - generate a new access token
         - save access token, token_expiry, and refresh_token to profile class instance
        :return: None
        """
        ...

    def set_profile_tokens(
        self, access_token: str, expires_at: datetime, refresh_token: Optional[str]
    ) -> None:
        """Set the profile tokens.

        :param token:
        :param expiry_time:
        :param refresh_token:
        :return:
        """
        self.profile.credentials.token = access_token
        self.profile.credentials.expires_at = expires_at.isoformat()
        self.profile.credentials.refresh_token = refresh_token
        self.profile.save_credentials()
