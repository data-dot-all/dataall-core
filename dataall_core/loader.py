"""Module to load GraphQL Schema."""

import json
import logging
import os
import re
from typing import Any, Optional, Tuple

from graphql import (
    GraphQLSchema,
    build_client_schema,
    is_enum_type,
    is_input_object_type,
    is_list_type,
    is_non_null_type,
    is_object_type,
    is_scalar_type,
    is_union_type,
    validate,
)
from graphql.language import parse

logger = logging.getLogger(__name__)

SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "schema")
MAX_DEPTH_QUERY = 3
MAX_DEPTH_MUTATION = 1

_first_cap_regex = re.compile("(.)([A-Z][a-z]+)")
_end_cap_regex = re.compile("([a-z0-9])([A-Z])")
_xform_cache: dict[Tuple[str, str], str] = {}


def xform_name(
    name: str, sep: str = "_", _xform_cache: dict[Tuple[str, str], str] = _xform_cache
) -> str:
    """Convert camel case to a "pythonic" name.

    If the name contains the ``sep`` character, then it is
    returned unchanged.

    """
    if sep in name:
        # If the sep is in the name, assume that it's already
        # transformed and return the string unchanged.
        return name
    key = (name, sep)
    if key not in _xform_cache:
        s1 = _first_cap_regex.sub(r"\1" + sep + r"\2", name)
        transformed = _end_cap_regex.sub(r"\1" + sep + r"\2", s1).lower()
        # Strip whitespace from transformed
        transformed = transformed.replace(" ", "")
        _xform_cache[key] = transformed
    return _xform_cache[key]


class Loader:
    """GraphQL Schema Loader."""

    schema: GraphQLSchema

    def __init__(
        self,
        max_depth_query: int = MAX_DEPTH_QUERY,
        max_depth_mutation: int = MAX_DEPTH_MUTATION,
    ) -> None:
        self.max_depth_query = max_depth_query
        self.max_depth_mutation = max_depth_mutation

    def load_schema(
        self, schema_path: Optional[str] = None, schema_version: Optional[str] = None
    ) -> None:
        """Load GraphQL Schema.

        Returns
        -------
        None

        """
        if schema_path:
            self.schema_path = schema_path
        else:
            logger.debug(f"Loading schema from default location {SCHEMA_DIR}")
            files = os.listdir(SCHEMA_DIR)
            files.sort()
            if schema_version:
                schema_version = (
                    schema_version + ".json"
                    if not schema_version.endswith(".json")
                    else schema_version
                )
                self.schema_path = os.path.join(SCHEMA_DIR, schema_version)
            else:
                logger.debug(
                    f"Loading schema version latest - {files[-1].rstrip('.json')}"
                )
                self.schema_path = os.path.join(SCHEMA_DIR, files[-1])

        logger.info(f"Loading Schema from path {self.schema_path}")
        with open(self.schema_path) as f:
            schema_json = json.load(f)
        self.schema = build_client_schema(schema_json)

    def create_graphql_dict(self) -> dict[str, dict[str, Any]]:
        """Create a dictionary of GraphQL operations.

        Returns
        -------
        - Dictionary of GraphQL operations.
        """
        op_dict = {}
        try:
            if self.schema.query_type:
                for field in self.schema.query_type.fields:
                    py_operation_name = xform_name(field)
                    (
                        query_string,
                        input_arguments,
                        flatten_args,
                    ) = self._build_query_string(field, "Query", self.max_depth_query)
                    docstring = self._build_docstring(field, self.schema.query_type)
                    validate(self.schema, parse(query_string))
                    op_dict[py_operation_name] = {
                        "query_definition": query_string,
                        "operation_name": field,
                        "docstring": docstring,
                        "input_args": input_arguments,
                        "flatten_input_args": flatten_args,
                    }
            if self.schema.mutation_type:
                for field in self.schema.mutation_type.fields:
                    py_operation_name = xform_name(field)
                    (
                        query_string,
                        input_arguments,
                        flatten_args,
                    ) = self._build_query_string(
                        field, "Mutation", self.max_depth_mutation
                    )
                    docstring = self._build_docstring(field, self.schema.mutation_type)
                    validate(self.schema, parse(query_string))
                    op_dict[py_operation_name] = {
                        "query_definition": query_string,
                        "operation_name": field,
                        "docstring": docstring,
                        "input_args": input_arguments,
                        "flatten_input_args": flatten_args,
                    }

        except Exception as e:
            logger.error(f"Found error loading GraphQL schema: {e}")
            raise e
        return op_dict

    def _resolve_base_type(self, field_type: Any) -> Any:
        while is_list_type(field_type) or is_non_null_type(field_type):
            field_type = field_type.of_type
        return field_type

    def _query_string_builder(
        self,
        type_name: str,
        field_name: str,
        max_depth: int,
        depth: int = 0,
        spacing: Optional[int] = None,
        input_args_dict: dict[str, Tuple[Any, Optional[str], bool]] = {},
    ) -> Tuple[str, dict[str, Any]]:
        """Get nested subfields and args for a given field up to a maximum depth.

        Args:
        ----
        - type_name: Name of the GraphQL type containing the field (i.e. Query or Mutation)
        - field_name: Name of the field (i.e. getEnvironment)
        - depth: Current depth of recursion

        Returns
        -------
        - GraphQL Query Defintion String
        - List of input arguments for the query/mutation

        """
        type_ = self.schema.get_type(type_name)

        # If Type not in Schema, return None
        if not type_ or not hasattr(type_, "fields"):
            return "", {}

        if not spacing:
            spacing = depth + 1
        tab_spacing = spacing * "  "

        query_string = tab_spacing

        field = type_.fields.get(field_name)
        if not field:
            return query_string, {}

        query_string += f"{field_name}"
        field_type = self._resolve_base_type(field.type)

        if field and depth <= max_depth:
            if field.args and depth + 1 <= max_depth:
                query_string += "("
                query_strings = []
                for arg_name, arg in field.args.items():
                    if arg_name in input_args_dict.keys():
                        input_args_dict[f"{field_name.lower()}_{arg_name}"] = (
                            arg.type,
                            arg.description,
                            is_non_null_type(arg.type),
                        )
                        query_strings.append(
                            f" {arg_name}: ${field_name.lower()}_{arg_name} "
                        )
                    else:
                        input_args_dict[arg_name] = (
                            arg.type,
                            arg.description,
                            is_non_null_type(arg.type),
                        )
                        query_strings.append(f" {arg_name}: ${arg_name} ")
                query_string += ", ".join(query_strings)
                query_string += ") "

            if is_scalar_type(field_type) or is_enum_type(field_type):
                pass
            elif is_object_type(field_type):
                if depth + 1 > max_depth:
                    return "", {}
                # For each field in the object type, recursively get subfields
                query_substring = ""
                nested_args = {}
                for subfield_name, _ in field_type.fields.items():
                    query_substring_part, nested_args_part = self._query_string_builder(
                        field_type.name,
                        subfield_name,
                        max_depth,
                        depth + 1,
                        spacing + 1,
                        input_args_dict,
                    )
                    query_substring += query_substring_part
                    nested_args.update(nested_args_part)
                if query_substring != "":
                    query_string += " { \n"
                    query_string += query_substring
                    query_string += tab_spacing + "}"

            elif is_union_type(field_type):
                if depth + 1 > max_depth:
                    return "", {}
                query_string += " { \n" + tab_spacing + "  __typename\n"
                for member_type in field_type.types:
                    query_substring = ""
                    nested_args = {}
                    for subfield_name, _ in member_type.fields.items():
                        (
                            query_substring_part,
                            nested_args_part,
                        ) = self._query_string_builder(
                            member_type.name,
                            subfield_name,
                            max_depth,
                            depth + 1,
                            spacing + 2,
                            input_args_dict,
                        )
                        query_substring += query_substring_part
                        nested_args.update(nested_args_part)

                    if query_substring != "":
                        query_string += (
                            f"{tab_spacing}  ... on {member_type.name} " + "{ \n"
                        )
                        query_string += query_substring
                        query_string += tab_spacing + "  }\n"
                query_string += tab_spacing + "}"

            else:
                return "", {}
        elif (
            field
            and not is_scalar_type(field.type)
            and not is_enum_type(field.type)
            and not is_list_type(field.type)
        ):
            return "", {}

        return query_string + "\n", input_args_dict

    def _flatten_inputs(
        self, input_obj: dict[Any, str], parent_key: str = "", sep: str = "."
    ) -> dict[str, Any]:
        """Flatten an input object recursively to expose input args as top level parameters (for CLI).

        Args:
        ----
        - input_obj: Input object to flatten
        - parent_key: Parent key for the input object
        - sep: Separator for nested keys

        Returns
        -------
        - Flattened input object

        """
        flattened = {}

        if hasattr(input_obj, "fields"):
            for field_name, field in input_obj.fields.items():
                p_key = parent_key + sep + field_name if parent_key else field_name

                if input_obj == field.type:
                    flattened[field_name] = (field.description, p_key)

                elif is_scalar_type(field.type) or (
                    is_non_null_type(field.type) and is_scalar_type(field.type.of_type)
                ):
                    flattened[field_name] = (field.description, p_key)

                elif is_list_type(field.type):
                    flattened[field_name] = (field.description, p_key)

                elif is_input_object_type(field.type):
                    flattened.update(self._flatten_inputs(field.type, p_key))
        return flattened

    def _build_query_string(
        self, operation_name: str, operation_kind: str, max_depth: int
    ) -> Tuple[str, dict[str, Any], dict[str, Any]]:
        """Build GraphQL compliant query strings for each query and mutation in schema.

        - Constructing the input arguments for the query/mutation
        - Constructing the subfields (i.e. return fields) for the query/mutation
        - Constructing the query/mutation string
        """
        flatten_input_args: dict[str, Tuple[Optional[str], str]] = {}
        input_args: dict[str, Tuple[Any, Optional[str], bool]] = {}

        query_string, input_args = self._query_string_builder(
            operation_kind, operation_name, max_depth=max_depth, input_args_dict={}
        )

        # Construct the input arguments for the query/mutation
        arguments_string = ""
        if len(input_args.items()):
            arguments_string = ", ".join(
                [
                    f"${name}: {value_type}"
                    for name, (value_type, _, _) in input_args.items()
                ]
            )
            arguments_string = "(" + arguments_string + ") "

        # The below is used to flatten inputs for required input args with nested inputs for CLI commands
        for arg_name, (arg_type, arg_description, required) in input_args.items():
            if required and is_input_object_type(arg_type.of_type):
                flatten_inputs = self._flatten_inputs(arg_type.of_type, arg_name)

                flatten_inputs_toadd = {}
                flatten_inputs_todel = []
                for k, v in flatten_inputs.items():
                    arg_name_og = k
                    _arg_name = k
                    index = 1
                    while _arg_name in flatten_input_args.keys():
                        _arg_name = _arg_name + "_" + str(index)
                        index += 1
                    flatten_inputs_toadd[_arg_name] = v
                    flatten_inputs_todel.append(arg_name_og)

                for i in flatten_inputs_todel:
                    del flatten_inputs[i]
                flatten_input_args.update(flatten_inputs_toadd)
                flatten_input_args.update(flatten_inputs)
            else:
                arg_name_og = arg_name
                _arg_name = arg_name
                if arg_name in flatten_input_args:
                    index = 1
                    while _arg_name in flatten_input_args.keys():
                        _arg_name = _arg_name + "_" + str(index)
                        index += 1
                flatten_input_args[_arg_name] = (arg_description, arg_name_og)

        query_string = f"""
{operation_kind.lower()} {operation_name} {arguments_string}{{
{query_string}
}}"""

        return query_string, input_args, flatten_input_args

    def _build_docstring(self, operation_name: str, operation_type: Any) -> str:
        """Build the docstring for the given operation using the descriptions present in schema."""
        docstring = ""
        api_desc = (
            operation_type.fields[operation_name].to_kwargs().get("description")
            or "This is a placeholder description of the operation"
        )
        api_description_str = f"{api_desc} \n\n"
        param_args = ""
        param_header = "\tParameters\n\t----------\n"
        for arg_name, arg in operation_type.fields[operation_name].args.items():
            param_args += f"\t{arg_name} : {arg.type}\n\t\t{arg.description or 'This is a placeholder description of the input field'}\n\n"

        if param_args:
            param_header += param_args

        field_type = self._resolve_base_type(operation_type.fields[operation_name].type)

        if is_list_type(field_type):
            return_type_name = field_type.of_type
            return_type_dtype = "List[Any]"
        elif is_object_type(field_type):
            return_type_name = field_type.name
            return_type_dtype = "dict[str, Any]"
        elif is_scalar_type(field_type):
            return_type_name = field_type.name
            return_type_dtype = str(field_type.name).lower()
        else:
            raise Exception
        return_header = (
            f"\tReturns\n\t-------\n\t{return_type_dtype}\n\t\t{return_type_name}\n"
        )
        return docstring + api_description_str + param_header + return_header
