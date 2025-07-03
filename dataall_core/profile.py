"""Module to retrieve data.all Profile information."""

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Tuple

import boto3
import yaml

from dataall_core.exceptions import (
    MissingParameterSecretException,
    MissingParametersException,
)

logger = logging.getLogger(__name__)


DEFAULT_PROFILE = "default"
CONFIG_PATH = Path.home().joinpath(".dataall", "config.yaml")
CREDENTIALS_PATH = Path.home().joinpath(".dataall", "credentials.yaml")


@dataclass
class ProfileCreds:
    """Data.all Profile Credentials Class."""

    token: Optional[str] = None
    expires_at: Optional[str] = None
    refresh_token: Optional[str] = None


class ConfigType(Enum):
    """Data.all Config Type Class."""

    LOCAL = "LOCAL"
    SECRET = "SECRET"  # nosec


class AuthType(Enum):
    """Data.all Config Type Class."""

    Custom = "CustomAuth"
    Cognito = "CognitoAuth"


@dataclass
class Profile:
    """Data.all Profile Class."""

    profile_name: str
    api_endpoint_url: str
    client_id: str
    redirect_uri: str
    idp_domain_url: str
    credentials: ProfileCreds = field(default_factory=ProfileCreds)
    client_secret: Optional[str] = None
    auth_type: str = AuthType.Cognito.value
    config_type: str = ConfigType.LOCAL.value
    auth_server: Optional[str] = "default"  # For Custom
    session_token_endpoint: Optional[str] = None  # For Custom
    username: Optional[str] = None  # For config stored in secret
    password: Optional[str] = None  # For config stored in secret
    creds_path: str = str(CREDENTIALS_PATH)

    def __post_init__(self) -> None:
        """Validate profile parameters."""
        if self.auth_type == AuthType.Custom.value and None in [
            self.session_token_endpoint,
        ]:
            raise MissingParametersException(
                "session_token_endpoint must be set if auth type is Custom"
            )

        if self.config_type not in [e.value for e in ConfigType]:
            raise ValueError(
                f"Invalid config type {self.config_type}. Must be one of {[e.value for e in ConfigType]}"
            )

        if self.auth_type not in [e.value for e in AuthType]:
            raise ValueError(
                f"Invalid auth type {self.auth_type}. Must be one of {[e.value for e in AuthType]}"
            )

        self.get_credentials()

    def get_credentials(self) -> None:
        """Get data.all profile credentials from the file.

        :param profile_name: data.all profile name
        :param creds_path: data.all credentials file path

        :return: data.all profile credentials
        """
        logger.info(
            f"Get credentials of profile {self.profile_name} from {self.creds_path}"
        )
        if os.path.isfile(self.creds_path):
            with open(self.creds_path) as file:
                creds = yaml.full_load(file)
                logger.debug(f"Retrieved creds: {creds}")
                if self.profile_name in creds:
                    self.credentials = ProfileCreds(
                        token=creds[self.profile_name].get("token", None),
                        expires_at=creds[self.profile_name].get("expires_at", None),
                        refresh_token=creds[self.profile_name].get(
                            "refresh_token", None
                        ),
                    )
                else:
                    logger.warn(
                        f"No credentials found for Profile {self.profile_name}..."
                    )
        else:
            logger.warn(f"Credentials file {self.creds_path} does not exist...")

    def save_credentials(self) -> None:
        """Save data.all profile credentials to the file.

        :param profile_name: data.all profile name
        :param profile_creds: data.all profile credentials
        :param creds_path: data.all credentials file path

        :return: None
        """
        try:
            Path(self.creds_path).parent.mkdir(parents=True, exist_ok=True)

            if not os.path.isfile(self.creds_path):
                with open(self.creds_path, "w+") as file:
                    yaml.dump({self.profile_name: asdict(self.credentials)}, file)
            else:
                with open(self.creds_path, "r") as file:
                    creds = yaml.full_load(file)

                if creds and self.profile_name in creds.keys():
                    creds.pop(self.profile_name)
                elif not creds:
                    creds = {}
                creds[self.profile_name] = asdict(self.credentials)

                with open(self.creds_path, "w") as file:
                    yaml.dump(creds, file)
        except Exception as e:
            logger.warn(
                f"Failed to save credentials at path {self.creds_path} due to: {e}"
            )
            logger.warn(
                f"Continuing without persisting token creds for profile {self.profile_name}..."
            )


def get_profile(
    profile: str = DEFAULT_PROFILE,
    config_path: Path = CONFIG_PATH,
    secret_arn: Optional[str] = None,
) -> Optional[Profile]:
    """Retrieve data.all config use ENV variable [dataall_config_path] to override default file location.

    :return: retrieved config from the file
    """
    if secret_arn is not None:
        config = get_profile_secret_value(secret_arn=secret_arn)
        config.update({"config_type": ConfigType.SECRET.value})
    else:
        config = get_profile_config_yaml(profile=profile, config_path=config_path)

    if config is None:
        return None
    return Profile(profile_name=profile, **config)


def get_profile_config_yaml(profile: str, config_path: Path) -> Any:
    """Retrieve data.all config use ENV variable [dataall_config_path] to override default file location.

    :return: retrieved config from the file
    """
    logger.info(f"Get config from {config_path}")
    if os.path.isfile(config_path):
        with open(config_path) as file:
            config = yaml.full_load(file)
            logger.debug(f"Retrieved config: {config}")
            if profile in config:
                return config[profile]
            else:
                logger.warn(
                    f"Profile {profile} is not configured for dataall_cli, please run configure() to set this profile..."
                )
                return
    else:
        logger.warn(
            f"Config file {config_path} does not exist, please the file {config_path} exists..."
        )
        return


def _parse_secret_arn(secret_arn: str) -> Tuple[str, Optional[str]]:
    arn_pattern = r"^arn:aws:secretsmanager:(.*?):(.*?):secret:(.*?)$"
    match = re.match(arn_pattern, secret_arn)
    if match:
        region = match.group(1)
        match.group(2)
        secret_id = match.group(3)
        return secret_id[:-7], region
    else:
        return "", None


def get_profile_secret_value(secret_arn: str) -> Any:
    """Retrieve data.all config from AWS Secret Manager based on provided secret_arn.

    :return: retrieved config from the file
    """
    secret_id, region = _parse_secret_arn(secret_arn)
    session = boto3.Session()
    try:
        client = session.client(service_name="secretsmanager", region_name=region)
        get_secret_value_response = client.get_secret_value(SecretId=secret_id)
    except Exception:
        raise MissingParameterSecretException(
            f"Parameter Secret {secret_arn} does not exist..."
        )

    secret = get_secret_value_response["SecretString"]
    return json.loads(secret)


def save_profile(profile: Profile, config_path: Path = CONFIG_PATH) -> None:
    """Save data.all config to the file."""
    logger.info(f"Save config to {config_path}")
    updated_profile_dict = asdict(
        profile,
        dict_factory=lambda x: {
            k: v
            for (k, v) in x
            if v is not None
            and (k not in ["profile_name", "username", "password", "credentials"])
        },
    )

    if not os.path.isfile(config_path):
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w+") as file:
            yaml.dump({profile.profile_name: updated_profile_dict}, file)
    else:
        with open(config_path, "r") as file:
            config = yaml.full_load(file)

        if config and profile.profile_name in config.keys():
            config.pop(profile.profile_name)
        elif not config:
            config = {}
        config[profile.profile_name] = updated_profile_dict

        with open(config_path, "w") as file:
            yaml.dump(config, file)
