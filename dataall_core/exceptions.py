"""GraphQL Exceptions."""

from typing import Any, Dict, List, Optional, Union

import httpx


class MissingParametersException(Exception):
    """Missing Parameters Exception."""


class MissingParameterSecretException(Exception):
    """Missing Parameters Exception."""


class GraphQLClientError(Exception):
    """GraphQL Base Exception."""


class GraphQLClientHttpError(GraphQLClientError):
    """GraphQL HTTP Error."""

    def __init__(self, status_code: int, response: httpx.Response) -> None:
        self.status_code = status_code
        self.response = response

    def __str__(self) -> str:
        """Return string representation."""
        return f"HTTP status code: {self.status_code}"


class GraphQLClientInvalidResponseError(GraphQLClientError):
    """GraphQL Invalid Response Error."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response

    def __str__(self) -> str:
        """Return string representation."""
        return "Invalid response format."


class GraphQLClientGraphQLError(GraphQLClientError):
    """GraphQL Client Error."""

    def __init__(
        self,
        message: str,
        locations: Optional[List[Dict[str, int]]] = None,
        path: Optional[List[str]] = None,
        extensions: Optional[Dict[str, object]] = None,
        orginal: Optional[Dict[str, object]] = None,
    ):
        self.message = message
        self.locations = locations
        self.path = path
        self.extensions = extensions
        self.orginal = orginal

    def __str__(self) -> str:
        """Return string representation."""
        return self.message

    @classmethod
    def from_dict(cls, error: Dict[str, Any]) -> "GraphQLClientGraphQLError":
        """Create from dict."""
        return cls(
            message=error["message"],
            locations=error.get("locations"),
            path=error.get("path"),
            extensions=error.get("extensions"),
            orginal=error,
        )


class GraphQLClientGraphQLMultiError(GraphQLClientError):
    """Multiple GraphQL Client Error."""

    def __init__(
        self,
        errors: List[GraphQLClientGraphQLError],
        data: Optional[Dict[str, Any]] = None,
    ):
        self.errors = errors
        self.data = data

    def __str__(self) -> str:
        """Return string representation."""
        return "; ".join(str(e) for e in self.errors)

    @classmethod
    def from_errors_dicts(
        cls, errors_dicts: List[Dict[str, Any]], data: Optional[Dict[str, Any]] = None
    ) -> "GraphQLClientGraphQLMultiError":
        """Create from dict."""
        return cls(
            errors=[GraphQLClientGraphQLError.from_dict(e) for e in errors_dicts],
            data=data,
        )


class GraphQLClientInvalidMessageFormat(GraphQLClientError):
    """Invalid Message Format."""

    def __init__(self, message: Union[str, bytes]) -> None:
        self.message = message

    def __str__(self) -> str:
        """Return string representation."""
        return "Invalid message format."
