from __future__ import annotations

import json
from unittest.mock import Mock

import httpx
import pytest

from datalens_sdk import (
    CloudEnvironment,
    CloudEnvironmentStorageSettings,
    DataLensClientYC,
    DataLensValidationError,
    LakehouseOperation,
    LakehouseTimestamp,
)
from datalens_sdk.domain.cloud_environment import CloudEnvironmentUpdate
from datalens_sdk.domain.navigation import Page
from datalens_sdk.domain.ports import CloudEnvironmentOperations


def test_cloud_environment_create_sends_schema_payload_and_returns_operation() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "operation-1", "done": False, "metadata": {}})

    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(handle))

    with client:
        operation = (
            client.create.cloud_environment(name="analytics", cloud_id="cloud-1", subnet_id="subnet-1")
            .description("Analytics compute")
            .security_group_ids(["sg-1"])
            .storage(max_size="1073741824")
            .build()
        )

    assert operation == LakehouseOperation(
        id="operation-1", done=False, metadata={}, raw={"id": "operation-1", "done": False, "metadata": {}}
    )
    assert [(request.url.path, json.loads(request.content)) for request in requests] == [
        (
            "/rpc/createCloudEnvironment",
            {
                "name": "analytics",
                "cloudId": "cloud-1",
                "subnetId": "subnet-1",
                "description": "Analytics compute",
                "securityGroupIds": ["sg-1"],
                "storage": {"maxSize": "1073741824"},
            },
        )
    ]


def test_cloud_environment_list_maps_timestamps_and_follows_page_tokens() -> None:
    requests: list[httpx.Request] = []
    environment = {
        "id": "environment-1",
        "name": "analytics",
        "createdAt": {"seconds": "1780000000", "nanos": 250},
        "createdById": "user-1",
        "updatedAt": {"seconds": "1780000010"},
        "updatedById": "user-2",
        "status": "READY",
        "statusDetails": "Ready",
        "cloudId": "cloud-1",
        "tenantId": "tenant-1",
        "subnetId": "subnet-1",
        "securityGroupIds": ["sg-1"],
        "description": "Analytics compute",
        "permissions": {"read": True},
        "storage": {"maxSize": "1073741824"},
    }

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if json.loads(request.content).get("pageToken") == "page-2":
            return httpx.Response(200, json={"cloudEnvironments": [], "nextPageToken": ""})
        return httpx.Response(200, json={"cloudEnvironments": [environment], "nextPageToken": "page-2"})

    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(handle))

    with client:
        pages = list(
            client.list.cloud_environments(
                filters=['name="analytics"'],
                include_permissions=False,
                page_size=1,
                page_token="page-1",
            ).pages()
        )

    assert pages == [
        Page(
            items=(
                CloudEnvironment(
                    id="environment-1",
                    name="analytics",
                    created_at=LakehouseTimestamp(seconds="1780000000", nanos=250),
                    created_by_id="user-1",
                    updated_at=LakehouseTimestamp(seconds="1780000010"),
                    updated_by_id="user-2",
                    status="READY",
                    status_details="Ready",
                    cloud_id="cloud-1",
                    tenant_id="tenant-1",
                    subnet_id="subnet-1",
                    security_group_ids=("sg-1",),
                    installation="yacloud",
                    description="Analytics compute",
                    permissions={"read": True},
                    storage=CloudEnvironmentStorageSettings(max_size="1073741824"),
                    raw=environment,
                ),
            ),
            next_page_token="page-2",
        ),
        Page(items=(), next_page_token=""),
    ]
    assert [(request.url.path, json.loads(request.content)) for request in requests] == [
        (
            "/rpc/listCloudEnvironments",
            {
                "filter": ['name="analytics"'],
                "includePermissions": False,
                "pageSize": 1,
                "pageToken": "page-1",
            },
        ),
        (
            "/rpc/listCloudEnvironments",
            {
                "filter": ['name="analytics"'],
                "includePermissions": False,
                "pageSize": 1,
                "pageToken": "page-2",
            },
        ),
    ]


def test_cloud_environment_refresh_update_and_delete_keep_resource_identity_and_clear_values() -> None:
    requests: list[httpx.Request] = []
    initial_raw = {
        "id": "environment-1",
        "name": "analytics",
        "createdAt": {"seconds": "1780000000"},
        "createdById": "user-1",
        "updatedAt": {"seconds": "1780000000"},
        "updatedById": "user-1",
        "status": "CREATING",
        "statusDetails": "Provisioning",
        "cloudId": "cloud-1",
        "tenantId": "tenant-1",
        "subnetId": "subnet-1",
        "securityGroupIds": ["sg-old"],
    }
    ready_raw = {
        "id": "environment-1",
        "name": "analytics",
        "createdAt": {"seconds": "1780000000"},
        "createdById": "user-1",
        "updatedAt": {"seconds": "1780000100"},
        "updatedById": "user-2",
        "status": "READY",
        "statusDetails": "Ready",
        "cloudId": "cloud-1",
        "tenantId": "tenant-1",
        "subnetId": "subnet-1",
        "securityGroupIds": ["sg-old"],
    }
    snapshots = [initial_raw, ready_raw]
    operations = [
        {"id": "update-1", "done": False, "metadata": {}},
        {"id": "delete-1", "done": False, "metadata": {}},
    ]

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/rpc/getCloudEnvironment":
            return httpx.Response(200, json=snapshots.pop(0))
        return httpx.Response(200, json=operations.pop(0))

    client = DataLensClientYC(auth=None, transport=httpx.MockTransport(handle))

    with client:
        initial = client.get.cloud_environment(by_id="environment-1", include_permissions=False)
        refreshed = initial.refresh(include_permissions=True)
        update_operation = refreshed.update().description("").security_group_ids([]).execute()
        delete_operation = refreshed.delete()

    assert initial.status == "CREATING"
    assert refreshed == CloudEnvironment(
        id="environment-1",
        name="analytics",
        created_at=LakehouseTimestamp(seconds="1780000000"),
        created_by_id="user-1",
        updated_at=LakehouseTimestamp(seconds="1780000100"),
        updated_by_id="user-2",
        status="READY",
        status_details="Ready",
        cloud_id="cloud-1",
        tenant_id="tenant-1",
        subnet_id="subnet-1",
        security_group_ids=("sg-old",),
        installation="yacloud",
        description=None,
        permissions=None,
        storage=None,
        raw=ready_raw,
    )
    assert update_operation == LakehouseOperation(
        id="update-1", done=False, metadata={}, raw={"id": "update-1", "done": False, "metadata": {}}
    )
    assert delete_operation == LakehouseOperation(
        id="delete-1", done=False, metadata={}, raw={"id": "delete-1", "done": False, "metadata": {}}
    )
    assert [(request.url.path, json.loads(request.content)) for request in requests] == [
        ("/rpc/getCloudEnvironment", {"id": "environment-1", "includePermissions": False}),
        ("/rpc/getCloudEnvironment", {"id": "environment-1", "includePermissions": True}),
        ("/rpc/updateCloudEnvironment", {"id": "environment-1", "description": "", "securityGroupIds": []}),
        ("/rpc/deleteCloudEnvironment", {"id": "environment-1"}),
    ]


def test_cloud_environment_update_rejects_empty_patch_before_sending_request() -> None:
    operations = Mock(spec=CloudEnvironmentOperations)
    builder = CloudEnvironmentUpdate(cloud_environment_id="environment-1", operations=operations)

    with pytest.raises(DataLensValidationError, match="at least one field"):
        builder.execute()

    operations.update_cloud_environment.assert_not_called()
