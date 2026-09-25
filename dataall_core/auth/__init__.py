"""Init Auth Clases."""

from .auth import AuthorizationClass
from .cognito_auth import CognitoAuth
from .custom_auth import CustomAuth
from .oidc_browser_auth import OidcBrowserAuth

__all__ = ["AuthorizationClass", "CognitoAuth", "CustomAuth", "OidcBrowserAuth"]
