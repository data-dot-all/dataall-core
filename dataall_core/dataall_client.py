"""Client which generates methods dynamically to BaseClient."""

import logging
from pathlib import Path
from typing import Any, Dict, Optional, cast

from dataall_core.auth import AuthorizationClass, CognitoAuth
from dataall_core.discovery import (
    frontend_origin,
    profile_from_frontend,
    profile_name_for,
)
from dataall_core.profile import (
    CONFIG_PATH,
    DEFAULT_PROFILE,
    Profile,
    get_profile,
    save_profile,
)

from .base_client import BaseClient
from .loader import Loader

_LOADER = Loader()

logger = logging.getLogger(__name__)


class DataallClient:
    """Client which generates methods dynamically to BaseClient."""

    def __init__(
        self,
        loader: Loader = _LOADER,
        schema_path: Optional[str] = None,
        schema_version: Optional[str] = None,
    ) -> None:
        self.loader = loader
        self.loader.load_schema(schema_path=schema_path, schema_version=schema_version)
        self.op_dict = self.loader.create_graphql_dict()

    def client(
        self,
        profile: Optional[str] = None,
        config_path: Optional[str] = None,
        secret_arn: Optional[str] = None,
        custom_headers: Dict[str, Any] = {},
        dataall_url: Optional[str] = None,
    ) -> BaseClient:
        """
        Create a client instance for data.all.

        ``dataall_url`` is the data.all front page. When the profile is not configured
        yet, the connection settings are read from that page and saved as a profile
        named after its host, so later calls skip the lookup.

        :return: BaseClient
        """
        class_attributes = {}
        py_name_to_operation_name = {}
        for py_operation_name in self.op_dict:
            class_attributes[py_operation_name] = self._create_api_method(
                py_operation_name=py_operation_name,
                operation_name=self.op_dict[py_operation_name]["operation_name"],
                operation_defintion=self.op_dict[py_operation_name]["query_definition"],
                input_args=self.op_dict[py_operation_name]["input_args"],
                docstring=self.op_dict[py_operation_name]["docstring"],
            )
            py_name_to_operation_name[py_operation_name] = self.op_dict[
                py_operation_name
            ]["operation_name"]
        class_attributes["_PY_TO_OP_NAME"] = py_name_to_operation_name
        bases = [BaseClient]

        cls = type("dataall", tuple(bases), class_attributes)

        path = Path(config_path or CONFIG_PATH)
        if dataall_url and not profile:
            profile = profile_name_for(dataall_url)
        da_profile = get_profile(
            profile=profile or DEFAULT_PROFILE, config_path=path, secret_arn=secret_arn
        )
        if dataall_url and da_profile is None:
            da_profile = profile_from_frontend(dataall_url, profile_name=profile)
            save_profile(da_profile, path)
        elif (
            dataall_url
            and da_profile
            and da_profile.frontend_url != frontend_origin(dataall_url)
        ):
            logger.warning(
                f"Profile {profile} points at {da_profile.frontend_url}, not {dataall_url}; using the profile"
            )

        authorizer = (
            self._find_authorizer(da_profile) if da_profile else CognitoAuth(da_profile)
        )

        return cast(
            BaseClient, cls(authorizer=authorizer, custom_headers=custom_headers)
        )

    def _find_authorizer(self, da_profile: Profile) -> AuthorizationClass:
        """Find the authorizer class for profile auth_type.

        :param da_profile:
        :return: AuthorizationClass
        """
        auth_class = next(
            (
                cls
                for cls in AuthorizationClass.__subclasses__()
                if cls.__name__ == da_profile.auth_type
            ),
            None,
        )
        if auth_class:
            auth_instance = auth_class(da_profile)  # type: ignore
        else:
            logger.error(
                f"No AuthorizationClass subclass found with name '{da_profile.auth_type}'"
            )
            raise Exception("No AuthorizationClass Found")
        return auth_instance

    def _create_api_method(
        self,
        py_operation_name: str,
        operation_name: str,
        operation_defintion: str,
        input_args: Dict[str, Any],
        docstring: str,
    ) -> Any:
        def _api_call(self, *args, **kwargs) -> Any:  # type: ignore
            # We're accepting *args so that we can give a more helpful
            # error message than TypeError: _api_call takes exactly
            # 1 argument.
            if args:
                raise TypeError(
                    f"{py_operation_name}() only accepts keyword arguments."
                )
            # The "self" in this scope is referring to the BaseClient.

            # Execute API
            return self.execute(operation_name, operation_defintion, kwargs)

        _api_call.__name__ = str(py_operation_name)

        # # Add the docstring to the client method
        _api_call.__doc__ = docstring
        return _api_call
