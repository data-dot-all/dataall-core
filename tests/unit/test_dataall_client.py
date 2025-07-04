import json
import uuid
from unittest.mock import MagicMock

import pytest
from graphql import GraphQLInputObjectType, GraphQLString

from dataall_core.base_client import BaseClient
from dataall_core.dataall_client import DataallClient
from dataall_core.loader import Loader


def sample_graphql_dict():
    return {
        "test_query1": {
            "operation_name": "testQuery1",
            "query_definition": "\nquery testQuery1 ($uri: String, $input2: String){\n  testQuery1(uri: $uri, input2: $input2)\n}",
            "docstring": "This is a placeholder description of the operation",
            "input_args": {"uri": GraphQLString, "input2": GraphQLString},
            "flatten_input_args": {"uri": (None, "uri"), "input2": (None, "input2")},
        },
        "test_mutation1": {
            "operation_name": "testMutation1",
            "query_definition": "\nmutation testMutation1 ($input: NewInput){\n  testMutation1(input: $input){\n    AwsAccountId\n    GlueCrawlerName\n    GlueCrawlerSchedule\n    GlueDatabaseName\n    GlueProfilingJobName\n    GlueProfilingTriggerSchedule\n    IAMDatasetAdminRoleArn\n    KmsAlias\n    S3BucketName\n    SamlAdminGroupName\n    admins\n    bucketCreated\n    bucketPolicyCreated\n    businessOwnerDelegationEmails\n    businessOwnerEmail\n    created\n    datasetUri\n    description\n    environment {\n      AwsAccountId\n      EnvironmentDefaultAthenaWorkGroup\n      EnvironmentDefaultBucketName\n      EnvironmentDefaultIAMRoleArn\n      EnvironmentDefaultIAMRoleImported\n      EnvironmentDefaultIAMRoleName\n      SamlGroupName\n      created\n      datasets\n      deleted\n      description\n      environmentType\n      environmentUri\n      isOrganizationDefaultEnvironment\n      label\n      name\n      owner\n      region\n      resourcePrefix\n      roleCreated\n      subscriptionsConsumersTopicImported\n      subscriptionsConsumersTopicName\n      subscriptionsEnabled\n      subscriptionsProducersTopicImported\n      subscriptionsProducersTopicName\n      updated\n      validated\n    }\n    glueDatabaseCreated\n    iamAdminRoleCreated\n    imported\n    importedAdminRole\n    importedGlueDatabase\n    importedKmsKey\n    importedS3Bucket\n    label\n    lakeformationLocationCreated\n    locations {\n      count\n      hasNext\n      hasPrevious\n      page\n      pages\n    }\n    name\n    organization {\n      SamlGroupName\n      created\n      description\n      label\n      name\n      organizationUri\n      owner\n      updated\n    }\n    owner\n    owners\n    region\n    shares {\n      count\n      hasNext\n      hasPrevious\n      nextPage\n      page\n      pageSize\n      pages\n      previousPage\n    }\n    stack {\n      EcsTaskArn\n      EcsTaskId\n      environmentUri\n      error\n      events\n      link\n      name\n      outputs\n      resources\n      stackUri\n      stackid\n      status\n    }\n    statistics {\n      locations\n      tables\n      upvotes\n    }\n    stewards\n    tables {\n      count\n      hasNext\n      hasPrevious\n      page\n      pages\n    }\n    tags\n    terms {\n      count\n      hasNext\n      hasPrevious\n      page\n      pages\n    }\n    updated\n\n  }\n}",
            "docstring": "This is a placeholder description of the operation \n\n\tParameters\n\t----------\n\tinput : NewInput\n\t\tThis is a placeholder description of the input field\n\n\tReturns\n\t-------\n\tDict[str, Any]\n\t\tDataset\n",
            "input_args": {
                "input": GraphQLInputObjectType(
                    "NewInput",
                    lambda: {
                        "SamlAdminGroupName": GraphQLString,
                        "description": GraphQLString,
                        "environmentUri": GraphQLString,
                        "label": GraphQLString,
                        "organizationUri": GraphQLString,
                        "owner": GraphQLString,
                        "tags": GraphQLString,
                        "topics": GraphQLString,
                    },
                )
            },
            "flatten_input_args": {
                "SamlAdminGroupName": (
                    "The SAML group name for the data pipeline",
                    "input.SamlAdminGroupName",
                ),
                "businessOwnerDelegationEmails": (
                    "The list of emails",
                    "input.businessOwnerDelegationEmails",
                ),
                "businessOwnerEmail": ("The owner email", "input.businessOwnerEmail"),
                "description": ("The dataset description", "input.description"),
                "environmentUri": ("The environment URI", "input.environmentUri"),
                "label": ("The dataset name", "input.label"),
                "organizationUri": ("The organization URI", "input.organizationUri"),
                "owner": ("The dataset owner team", "input.owner"),
                "stewards": ("The dataset steward team", "input.stewards"),
                "tags": ("The list of dataset tags", "input.tags"),
                "topics": ("The list of dataset topics", "input.topics"),
            },
        },
    }


@pytest.fixture(scope="module")
def mock_loader():
    mock_loader = MagicMock(spec=Loader)
    mock_loader.load_schema.return_value = {}
    mock_loader.create_graphql_dict.return_value = sample_graphql_dict()
    yield mock_loader


@pytest.fixture
def mock_sub(mocker):
    yield mocker.patch("re.sub")


def test_dataall_client_init_default():
    client = DataallClient()
    assert isinstance(client.loader, Loader)
    assert client.op_dict
    assert len(client.op_dict)


def test_dataall_client_init_schema_version():
    client = DataallClient(schema_version="v2_5")
    assert isinstance(client.loader, Loader)
    assert client.op_dict
    assert len(client.op_dict)


def test_dataall_client_init_mock_loader(mock_loader):
    client = DataallClient(loader=mock_loader)

    assert isinstance(client.loader, Loader)
    assert client.op_dict
    assert len(client.op_dict) == 2
    assert "test_query1" in client.op_dict.keys()
    assert "test_mutation1" in client.op_dict.keys()


def test_dataall_client_create_methods_default(mock_loader):
    client = DataallClient(loader=mock_loader)
    base_client = client.client(config_path=f"{uuid.uuid4()}.yaml")
    assert isinstance(base_client, BaseClient)
    assert getattr(base_client, "test_query1") and callable(
        getattr(base_client, "test_query1")
    )
    assert (
        getattr(base_client, "test_query1").__doc__
        == "This is a placeholder description of the operation"
    )
    assert getattr(base_client, "test_mutation1") and callable(
        getattr(base_client, "test_mutation1")
    )
    assert json.dumps(getattr(base_client, "test_mutation1").__doc__)
    assert base_client.authorizer.profile is None

    with pytest.raises(TypeError) as e:
        non_kwarg = "non_kwarg"
        getattr(base_client, "test_query1")(non_kwarg)
        assert e == "test_query1() only accepts keyword arguments."
