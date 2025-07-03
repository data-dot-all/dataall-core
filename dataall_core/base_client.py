"""BaseClient for data.all client instance."""

import json
import logging
from typing import Any, Dict, Optional, cast

import httpx
from retrying import retry

from dataall_core.auth import AuthorizationClass
from dataall_core.exceptions import (
    GraphQLClientGraphQLMultiError,
    GraphQLClientHttpError,
    GraphQLClientInvalidResponseError,
)

logger = logging.getLogger(__name__)


QUERY_ENDPOINT = "/graphql/api"
SEARCH_ENDPOINT = "/search/api"


class BaseClient:
    """data.all client class to execute APIs against the endpoint."""

    http_client: httpx.Client

    def __init__(
        self, authorizer: AuthorizationClass, custom_headers: Dict[str, Any] = {}
    ):
        """Initialize Client for a profile.

        :param profile:
        """
        logger.info("Initialize client...")
        self.authorizer = authorizer
        self.custom_headers = custom_headers

    def execute(
        self, operation_name: str, query: str, api_params: Dict[Any, Any]
    ) -> Any:
        """
        Execute a query against the API.

        :return: dict
        """
        self.http_client = httpx.Client(
            headers={
                "Authorization": f"Bearer {self.authorizer.get_jwt_token()}",
                **self.custom_headers,
            }
        )
        response = self._execute(
            query=query,
            operation_name=operation_name,
            variables=api_params,
        )
        return self.get_data(response).get(operation_name, {})

    def get_data(self, response: httpx.Response) -> Dict[str, Any]:
        """
        Get data from response.

        :return: dict
        """
        if not response.is_success:
            raise GraphQLClientHttpError(
                status_code=response.status_code, response=response
            )
        try:
            response_json = response.json()
        except ValueError as exc:
            raise GraphQLClientInvalidResponseError(response=response) from exc

        if (not isinstance(response_json, dict)) or (
            "data" not in response_json and "errors" not in response_json
        ):
            raise GraphQLClientInvalidResponseError(response=response)

        data = response_json.get("data")
        errors = response_json.get("errors")

        if errors:
            raise GraphQLClientGraphQLMultiError.from_errors_dicts(
                errors_dicts=errors, data=data
            )

        return cast(Dict[str, Any], data)

    @retry(stop_max_attempt_number=3, wait_random_min=1000, wait_random_max=3000)  # type: ignore
    def _execute(
        self,
        query: str,
        operation_name: Optional[str],
        variables: Dict[str, Any],
        **kwargs: Any,
    ) -> httpx.Response:
        return self.http_client.post(
            url=self.authorizer.profile.api_endpoint_url + QUERY_ENDPOINT,
            timeout=20,
            content=json.dumps(
                {
                    "query": query,
                    "operationName": operation_name,
                    "variables": variables,
                },
            ),
        )
