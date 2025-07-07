import json
import os
from pathlib import Path

import boto3
import moto
import pytest

from dataall_core.exceptions import (
    MissingParameterSecretException,
    MissingParametersException,
)
from dataall_core.profile import (
    AuthType,
    ConfigType,
    Profile,
    get_profile,
    get_profile_config_yaml,
    get_profile_secret_value,
    save_profile,
)

PROFILE_CONFIG = Path(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "test_profile", "config.yaml"
    )
)

PROFILE_CREDS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "test_profile", "credentials.yaml"
)


@pytest.fixture(autouse=True)
def cleanup_creds():
    yield
    if os.path.exists(PROFILE_CREDS):
        os.remove(PROFILE_CREDS)


@pytest.fixture(scope="function")
def aws_credentials():
    """Mocked AWS Credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture(scope="function")
def secret_profile_name():
    return "SecretName"


@pytest.fixture(scope="function")
def secret_profile_arn(secret_profile_name):
    return f"arn:aws:secretsmanager:us-east-1:11111111111:secret:{secret_profile_name}-XXXXXX"


@pytest.fixture(scope="function")
def aws_secretsmanager(aws_credentials):
    with moto.mock_aws():
        yield boto3.client("secretsmanager", region_name="us-east-1")


@pytest.fixture(scope="module")
def base_profile_params():
    return {
        "profile_name": "default",
        "api_endpoint_url": "XXXXXXXXXXXXXXXX",
        "client_id": "client_id",
        "redirect_uri": "XXXXXXXXXXXXXXXX",
        "idp_domain_url": "XXXXXXXXXXXXXXXX",
        "creds_path": PROFILE_CREDS,
    }


@pytest.fixture(scope="module")
def base_profile_params_missing():
    return {"profile_name": "default"}


@pytest.fixture(scope="module")
def custom_profile_params():
    return {
        "session_token_endpoint": "XXXXXXXXXXXXXXXX",
        "auth_type": AuthType.Custom.value,
    }


@pytest.fixture
def create_secret(aws_secretsmanager, secret_profile_name, base_profile_params):
    final_params = {**base_profile_params}
    del final_params["profile_name"]
    final_params.update({"username": "username", "password": "password"})
    boto3.client("secretsmanager").create_secret(
        Name=secret_profile_name, SecretString=json.dumps(final_params)
    )


@pytest.fixture
def create_secret_custom(
    aws_secretsmanager, secret_profile_name, base_profile_params, custom_profile_params
):
    final_params = {**base_profile_params, **custom_profile_params}
    del final_params["profile_name"]
    final_params.update({"username": "username", "password": "password"})
    boto3.client("secretsmanager").create_secret(
        Name=secret_profile_name, SecretString=json.dumps(final_params)
    )


def test_profile_no_params():
    """Test if Profile() parameters are missing assert exception raised"""
    with pytest.raises(TypeError):
        Profile()


def test_profile_missing_cognito(base_profile_params_missing):
    """Test if Profile() parameters are missing assert exception raised"""
    with pytest.raises(TypeError):
        Profile(**base_profile_params_missing)


def test_profile_cognito(base_profile_params):
    """Test if Profile() parameters are missing assert exception raised"""
    profile = Profile(**base_profile_params)
    assert profile
    for k, v in base_profile_params.items():
        assert getattr(profile, k) == v
    assert profile.auth_type == AuthType.Cognito.value
    assert profile.config_type == ConfigType.LOCAL.value


def test_profile_config_type_value_error(base_profile_params):
    """Test if local configured Profile() username password assert error"""
    with pytest.raises(ValueError):
        Profile(**base_profile_params, config_type="NEW_CONFIG")


def test_profile_auth_type_value_error(base_profile_params):
    """Test if local configured Profile() username password assert error"""
    with pytest.raises(ValueError):
        Profile(**base_profile_params, auth_type="NEW_AUTH")


def test_profile_missing_custom(base_profile_params):
    """Test if Profile() parameters are missing assert exception raised"""
    with pytest.raises(MissingParametersException):
        Profile(**base_profile_params, auth_type=AuthType.Custom.value)


def test_profile_custom(base_profile_params, custom_profile_params):
    profile = Profile(**base_profile_params, **custom_profile_params)
    assert profile
    for k, v in base_profile_params.items():
        assert getattr(profile, k) == v
    for k, v in custom_profile_params.items():
        assert getattr(profile, k) == v


def test_get_profile_config_yaml_dne(mocker):
    mocker.patch("os.path.isfile", return_value=False)
    config = get_profile_config_yaml("default", PROFILE_CONFIG)
    assert config is None


def test_get_profile_config_yaml():
    config = get_profile_config_yaml("CognitoDefault", PROFILE_CONFIG)
    assert config
    assert len(config) == 8


def test_get_profile_config_yaml_custom():
    config = get_profile_config_yaml("CustomDefault", PROFILE_CONFIG)
    assert config
    assert len(config) == 7


def test_get_profile_config_yaml_profile_dne():
    config = get_profile_config_yaml("ProfileDNE", PROFILE_CONFIG)
    assert config is None


def test_get_profile_secret_value_dne():
    with pytest.raises(MissingParameterSecretException):
        get_profile_secret_value("i-do-not-exist")


def test_get_profile_secret_value(create_secret, secret_profile_arn):
    config = get_profile_secret_value(secret_profile_arn)
    assert config
    assert len(config) == 7


def test_get_profile_secret_value_custom(create_secret_custom, secret_profile_arn):
    config = get_profile_secret_value(secret_profile_arn)
    assert config
    assert len(config) == 9


def test_get_profile_dne():
    profile = get_profile(profile="doesNotExist")
    assert profile is None


def test_get_profile():
    profile = get_profile(profile="CognitoDefault", config_path=PROFILE_CONFIG)
    assert isinstance(profile, Profile)


def test_get_profile_custom():
    profile = get_profile(profile="CustomDefault", config_path=PROFILE_CONFIG)
    assert isinstance(profile, Profile)


def test_get_profile_secret(create_secret, secret_profile_arn):
    profile = get_profile(profile="secrets", secret_arn=secret_profile_arn)
    assert isinstance(profile, Profile)
    assert profile.config_type == ConfigType.SECRET.value


def test_save_profile():
    profile_name = "CognitoDefault"
    profile = get_profile(profile=profile_name, config_path=PROFILE_CONFIG)
    assert profile

    profile.creds_path = PROFILE_CREDS
    profile_params = profile.__dict__

    save_profile(profile=profile, config_path=PROFILE_CONFIG)
    profile = get_profile(profile=profile_name, config_path=PROFILE_CONFIG)

    for k, v in profile_params.items():
        assert getattr(profile, k) == v

    assert isinstance(profile, Profile)
