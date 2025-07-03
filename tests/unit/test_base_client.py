import os
from unittest.mock import patch

import httpx
import pytest
import respx

from dataall_core.auth import AuthorizationClass, CustomAuth
from dataall_core.base_client import QUERY_ENDPOINT, BaseClient
from dataall_core.exceptions import (
    GraphQLClientGraphQLMultiError,
    GraphQLClientHttpError,
    GraphQLClientInvalidResponseError,
)
from dataall_core.profile import AuthType, ConfigType, Profile

USERNAME = "Username"
PASSWORD = "Test123!"

URL = "https://da-api-endpoint.com/tst"

PROFILE_CREDS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "test_profile", "credentials.yaml"
)


@pytest.fixture(scope="module")
def custom_profile():
    return Profile(
        profile_name="default",
        auth_type=AuthType.Custom.value,
        api_endpoint_url="https://da-api-endpoint.com/tst",
        username=USERNAME,
        password=PASSWORD,
        client_id="client_id",
        redirect_uri="https://dataall-test.com/",
        idp_domain_url="https://custom-idp.com/",
        session_token_endpoint="https://custom-idp.com/session/endpoint",
        config_type=ConfigType.SECRET.value,
    )


@pytest.fixture
def mock_get_jwt_token():
    with patch.object(AuthorizationClass, "get_jwt_token") as mock_method:
        mock_method.return_value = "sampletoken"
        yield mock_method


@pytest.fixture(scope="module")
def mocked_custom_api():
    with respx.mock(base_url=URL) as respx_mock:
        yield respx_mock


@pytest.fixture
def mock_query_success(mocked_custom_api):
    api_endpoints = mocked_custom_api.post(QUERY_ENDPOINT, name="api_endpoints")
    api_endpoints.return_value = httpx.Response(
        200, json={"data": {"tstOperation": {"somekey": "somevalue"}}}
    )


@pytest.fixture
def mock_query_error(mocked_custom_api):
    api_endpoints = mocked_custom_api.post(QUERY_ENDPOINT, name="api_endpoints")
    api_endpoints.return_value = httpx.Response(
        200,
        json={
            "data": {"somekey": "somevalue"},
            "errors": [{"message": "error1"}, {"message": "error2"}],
        },
    )


@pytest.fixture
def mock_query_invalid_response1(mocked_custom_api):
    api_endpoints = mocked_custom_api.post(QUERY_ENDPOINT, name="api_endpoints")
    api_endpoints.return_value = httpx.Response(
        200, json={"randomkey": {"somekey": "somevalue"}}
    )


@pytest.fixture
def mock_query_invalid_response2(mocked_custom_api):
    api_endpoints = mocked_custom_api.post(QUERY_ENDPOINT, name="api_endpoints")
    api_endpoints.return_value = httpx.Response(200, text="non-json reponse")


@pytest.fixture
def mock_query_error_code(mocked_custom_api):
    api_endpoints = mocked_custom_api.post(QUERY_ENDPOINT, name="api_endpoints")
    api_endpoints.return_value = httpx.Response(404, text="non-json reponse")


def test_base_client_execute(mock_query_success, mock_get_jwt_token, custom_profile):
    auth = CustomAuth(profile=custom_profile)
    base_client = BaseClient(authorizer=auth)
    response = base_client.execute(
        operation_name="tstOperation", query="query testQuery1 (){ }", api_params={}
    )
    assert response
    assert response == {"somekey": "somevalue"}


def test_base_client_execute_custom_headers(
    mocked_custom_api, mock_query_success, mock_get_jwt_token, custom_profile
):
    auth = CustomAuth(profile=custom_profile)
    base_client = BaseClient(
        authorizer=auth, custom_headers={"X-Custom-Header": "custom-value"}
    )
    base_client.execute(
        operation_name="tstOperation", query="query testQuery1 (){ }", api_params={}
    )

    request = mocked_custom_api.calls[-1].request

    assert "X-Custom-Header" in request.headers
    assert request.headers["X-Custom-Header"] == "custom-value"


def test_base_client_execute_error(
    mock_query_error, mock_get_jwt_token, custom_profile
):
    auth = CustomAuth(profile=custom_profile)
    base_client = BaseClient(authorizer=auth)

    with pytest.raises(GraphQLClientGraphQLMultiError) as e:
        base_client.execute(
            operation_name="tstOperation", query="query testQuery1 (){ }", api_params={}
        )
    assert str(e.value) == "error1; error2"


def test_base_client_invalid_response1(
    mock_query_invalid_response1, mock_get_jwt_token, custom_profile
):
    auth = CustomAuth(profile=custom_profile)
    base_client = BaseClient(authorizer=auth)

    with pytest.raises(GraphQLClientInvalidResponseError) as e:
        base_client.execute(
            operation_name="tstOperation", query="query testQuery1 (){ }", api_params={}
        )
    assert str(e.value) == "Invalid response format."


def test_base_client_invalid_response2(
    mock_query_invalid_response2, mock_get_jwt_token, custom_profile
):
    auth = CustomAuth(profile=custom_profile)
    base_client = BaseClient(authorizer=auth)

    with pytest.raises(GraphQLClientInvalidResponseError) as e:
        base_client.execute(
            operation_name="tstOperation", query="query testQuery1 (){ }", api_params={}
        )
    assert str(e.value) == "Invalid response format."


def test_base_client_error_code(
    mock_query_error_code, mock_get_jwt_token, custom_profile
):
    auth = CustomAuth(profile=custom_profile)
    base_client = BaseClient(authorizer=auth)

    with pytest.raises(GraphQLClientHttpError) as e:
        base_client.execute(
            operation_name="tstOperation", query="query testQuery1 (){ }", api_params={}
        )
    assert str(e.value) == "HTTP status code: 404"
