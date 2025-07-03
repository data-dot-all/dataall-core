import logging
import os

import httpx
import pytest
import requests_mock
import respx

from dataall_core.auth import CognitoAuth, CustomAuth
from dataall_core.profile import AuthType, ConfigType, Profile

logger = logging.getLogger("dataall_core").setLevel(logging.DEBUG)

USERNAME = "Username"
PASSWORD = "Test123!"

PROFILE_CREDS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "test_profile", "credentials.yaml"
)


@pytest.fixture(autouse=True)
def cleanup_creds():
    yield
    if os.path.exists(PROFILE_CREDS):
        os.remove(PROFILE_CREDS)


@pytest.fixture(scope="function")
def cognito_profile():
    return Profile(
        profile_name="CognitoDefault",
        auth_type=AuthType.Cognito.value,
        api_endpoint_url="https://da-api-endpoint.com/tst",
        username=USERNAME,
        password=PASSWORD,
        client_id="client_id",
        redirect_uri="https://dataall-test.com/",
        idp_domain_url="https://cognito-idp.com/",
        creds_path=PROFILE_CREDS,
        config_type=ConfigType.SECRET.value,
    )


@pytest.fixture(scope="function")
def custom_profile():
    return Profile(
        profile_name="CustomDefault",
        auth_type=AuthType.Custom.value,
        api_endpoint_url="https://da-api-endpoint.com/tst",
        username=USERNAME,
        password=PASSWORD,
        client_id="client_id",
        redirect_uri="https://dataall-test.com/",
        idp_domain_url="https://custom-idp.com/",
        session_token_endpoint="https://custom-idp.com/session/endpoint",
        creds_path=PROFILE_CREDS,
        config_type=ConfigType.SECRET.value,
    )


@pytest.fixture(scope="function")
def mocked_cognito_api(cognito_profile):
    login_endpoint = "/login"
    token_endpoint = "/oauth2/token"

    with requests_mock.Mocker() as mock:
        mock.register_uri(
            "POST",
            login_endpoint,
            status_code=200,
            headers={
                "location": f"{cognito_profile.idp_domain_url}{login_endpoint}?code=1X1X1AUTHCODE1X1X1&state=xyz"
            },
        )
        mock.register_uri(
            "POST",
            token_endpoint,
            status_code=200,
            json={
                "access_token": "sampleAccessTokenValueHere",
                "expires_in": 3600,
                "refresh_token": "sampleRefreshTokenValueHere",
            },
        )
        yield mock


@pytest.fixture(scope="function")
def mocked_custom_api(custom_profile):
    auth_endpoint = "/tst/auth"
    token_endpoint = "/tst/token"
    with respx.mock(base_url=f"{custom_profile.idp_domain_url}") as respx_mock:
        # Mock Get Endpoints - .well-known/openid-configuration (Not supported by moto mocker)
        openid_endpoints = respx_mock.get(
            "/.well-known/openid-configuration", name="openid_endpoints"
        )
        openid_endpoints.return_value = httpx.Response(
            200,
            json={
                "authorization_endpoint": f"{custom_profile.idp_domain_url}{auth_endpoint}",
                "token_endpoint": f"{custom_profile.idp_domain_url}{token_endpoint}",
            },
        )
        # Mock Get Session Token Endpoint
        session_token_endpoint = respx_mock.post(
            f"{'/'.join(custom_profile.session_token_endpoint.split('/')[3:])}",
            name="session_token_endpoint",
        )
        session_token_endpoint.return_value = httpx.Response(
            200,
            json={
                "sessionToken": "test-session-token",
            },
        )
        # Mock Get Session Token Endpoint
        session_token_endpoint = respx_mock.get(auth_endpoint, name="auth_endpoint")
        session_token_endpoint.return_value = httpx.Response(
            200,
            html="""
<html>

<head>
  <title>Authorization Response</title>
</head>

<body>
  <form method="POST" action="https://example.com/token"> <input type="hidden" name="code"
      value="1X1X1AUTHCODE1X1X1"> <input type="hidden" name="state" value="xyz"> </form>
  <script> document.forms[0].submit(); </script>
</body>

</html>
""",
        )
        session_token_endpoint = respx_mock.post(token_endpoint, name="token_endpoint")
        session_token_endpoint.return_value = httpx.Response(
            200,
            json={
                "access_token": "sampleTokenValueHere",
                "expires_in": 3600,
            },
        )

        yield respx_mock


def test_init_no_profile():
    auth = CognitoAuth()
    assert auth.profile is None


def test_init(cognito_profile):
    auth = CognitoAuth(cognito_profile)
    assert auth.profile == cognito_profile


def test_authenticate_and_get_token_cognito(cognito_profile, mocked_cognito_api):
    auth = CognitoAuth(cognito_profile)
    token = auth.get_jwt_token()
    assert auth.profile.credentials.token
    assert auth.profile.credentials.expires_at
    assert auth.profile.credentials.refresh_token

    token2 = auth.get_jwt_token()
    assert token == token2


def test_authenticate_and_get_token_cognito_refresh(
    mocked_cognito_api, cognito_profile
):
    auth = CognitoAuth(cognito_profile)
    auth.get_jwt_token()

    assert auth.profile.credentials.token
    assert auth.profile.credentials.expires_at
    assert auth.profile.credentials.refresh_token

    # When token expiry is met - assert new token can be accessed via refresh token
    auth.profile.credentials.expires_at = None
    auth.get_jwt_token()

    assert auth.profile.credentials.token
    assert auth.profile.credentials.expires_at
    assert auth.profile.credentials.refresh_token


def test_authenticate_and_get_token_custom(custom_profile, mocked_custom_api):
    # Get Token Custom Auth
    auth = CustomAuth(custom_profile)
    auth.get_jwt_token()
    assert auth.profile.credentials.token
    assert auth.profile.credentials.expires_at


def test_authenticate_and_get_token_no_profile():
    auth = CognitoAuth()
    with pytest.raises(Exception):
        auth.get_jwt_token()
