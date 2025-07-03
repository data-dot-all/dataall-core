import logging
import os

import pytest
from graphql import assert_valid_schema

from dataall_core.loader import (
    MAX_DEPTH_MUTATION,
    MAX_DEPTH_QUERY,
    SCHEMA_DIR,
    Loader,
    xform_name,
)

logging.getLogger("dataall_core").setLevel(logging.DEBUG)

EXAMPLE_SCHEMAS_DIR = os.path.join(os.path.dirname(__file__), "test_schema")
EXAMPLE_SCHEMAS = os.listdir(EXAMPLE_SCHEMAS_DIR)


@pytest.fixture(scope="function")
def default_loader():
    yield Loader()


@pytest.fixture
def mock_sub(mocker):
    yield mocker.patch("re.sub")


def test_xform_name_transform():
    fields = [
        ("testCreate", "test_create"),
        ("TestCreate", "test_create"),
        ("TESTCREATE", "testcreate"),
        ("testcreatE", "testcreat_e"),
        ("testCREATE", "test_create"),
        ("    TESTCREATE     ", "testcreate"),
    ]
    for field in fields:
        assert xform_name(field[0]) == field[1]


def test_xform_name_unchanged():
    fields = ["test_create", "TEST_CREATE", "Test_Create", "    TEST_CREATE     "]
    for field in fields:
        assert xform_name(field) == field


def test_xform_name_new_sep():
    fields = [
        ("testCreate", "test.create"),
        ("TESTCREATE", "testcreate"),
        ("testcreatE", "testcreat.e"),
        ("testCREATE", "test.create"),
        ("    TESTCREATE     ", "testcreate"),
        ("Test.Create", "Test.Create"),
        ("test_cREATE", "test_c.reate"),
    ]
    for field in fields:
        assert xform_name(field[0], sep=".") == field[1]


def test_xform_name_cache(mock_sub):
    xform_cache = {("testCreate", "_"): "test_create"}
    transformed_name = xform_name("testCreate", _xform_cache=xform_cache)
    assert transformed_name == "test_create"
    assert mock_sub.call_count == 0


def test_loader_init():
    loader = Loader(max_depth_query=5, max_depth_mutation=3)
    assert loader.max_depth_query == 5
    assert loader.max_depth_mutation == 3
    assert not hasattr(loader, "schema_path")
    assert not hasattr(loader, "schema")


def test_loader_init_default():
    loader = Loader()
    assert loader.max_depth_query == MAX_DEPTH_QUERY
    assert loader.max_depth_mutation == MAX_DEPTH_MUTATION
    assert not hasattr(loader, "schema_path")
    assert not hasattr(loader, "schema")


def test_load_schema_default():
    loader = Loader()
    loader.load_schema()
    files = os.listdir(SCHEMA_DIR)
    files.sort()
    assert loader.schema_path == os.path.join(SCHEMA_DIR, files[-1])
    assert loader.schema
    assert_valid_schema(loader.schema)


def test_load_schema_versions():
    files = os.listdir(SCHEMA_DIR)
    files.sort()
    for f in files:
        loader = Loader()
        loader.load_schema(schema_version=f.split(".")[0])
        assert loader.schema_path == os.path.join(SCHEMA_DIR, f)
        assert loader.schema
        assert_valid_schema(loader.schema)


def test_load_schema_empty_path():
    loader = Loader()
    with pytest.raises(FileNotFoundError):
        loader.load_schema(
            schema_path=f"{os.path.dirname(__file__)}/file_path_does_not_exist"
        )


@pytest.mark.parametrize("filename", EXAMPLE_SCHEMAS)
def test_load_schema_alternatives(filename):
    loader = Loader()
    loader.load_schema(schema_path=os.path.join(EXAMPLE_SCHEMAS_DIR, filename))
    assert loader.schema
    assert_valid_schema(loader.schema)


def test_create_graphql_dict_default():
    loader = Loader()
    loader.load_schema()
    graphql_dict = loader.create_graphql_dict()
    assert graphql_dict
    assert len(graphql_dict) == len(loader.schema.query_type.fields) + len(
        loader.schema.mutation_type.fields
    )


@pytest.mark.parametrize("filename", EXAMPLE_SCHEMAS)
def test_create_graphql_dict_alts(filename):
    loader = Loader()
    loader.load_schema(schema_path=os.path.join(EXAMPLE_SCHEMAS_DIR, filename))
    graphql_dict = loader.create_graphql_dict()
    assert graphql_dict
    assert len(graphql_dict) == len(loader.schema.query_type.fields) + len(
        loader.schema.mutation_type.fields
    )


@pytest.mark.parametrize("max_depth", [1, 2, 3, 4])
def test_create_graphql_dict_max_depths(max_depth):
    loader = Loader(max_depth_query=max_depth, max_depth_mutation=max_depth)
    loader.load_schema()
    graphql_dict = loader.create_graphql_dict()
    assert graphql_dict
    assert len(graphql_dict) == len(loader.schema.query_type.fields) + len(
        loader.schema.mutation_type.fields
    )
    print(type(loader.schema))
    assert_valid_schema(loader.schema)
