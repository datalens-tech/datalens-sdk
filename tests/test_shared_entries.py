from __future__ import annotations

from dataclasses import fields
import json
from pathlib import Path
from typing import get_type_hints

import httpx
from pydantic import BaseModel
import pytest

from datalens_sdk import DataLensClientEnterprise, DataLensClientYC, codegen
from datalens_sdk._generated import dto
from datalens_sdk.domain.shared_entries import (
    SharedEntryBindingEntry,
    SharedEntryBindingEntryPermissions,
    SharedEntryBindingWorkbook,
    SharedEntryBindingWorkbookPermissions,
)
from datalens_sdk.errors import DTOValidationError


def test_shared_binding_operations_use_spec_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"sourceId": "connection-1", "targetId": "workbook-1", "isDelegated": True})

    with DataLensClientYC(auth=None, transport=httpx.MockTransport(handler)) as client:
        result = client.shared_entries.bind(source_id="connection-1", target_id="workbook-1", delegation=True)
        assert result.is_delegated is True
        client.shared_entries.update(source_id="connection-1", target_id="workbook-1", delegation=False)
        client.shared_entries.unbind(source_id="connection-1", target_id="workbook-1")
        client.shared_entries.get_delegation(source_id="connection-1", target_id="workbook-1")

    assert [request.url.path for request in requests] == [
        "/rpc/createSharedEntryBinding",
        "/rpc/updateSharedEntryBinding",
        "/rpc/deleteSharedEntryBinding",
        "/rpc/getSharedEntryDelegation",
    ]
    assert [json.loads(request.content) for request in requests] == [
        {"sourceId": "connection-1", "targetId": "workbook-1", "delegation": True},
        {"sourceId": "connection-1", "targetId": "workbook-1", "delegation": False},
        {"sourceId": "connection-1", "targetId": "workbook-1"},
        {"sourceId": "connection-1", "targetId": "workbook-1"},
    ]


def test_shared_binding_listing_paginates_mixed_targets() -> None:
    requests: list[httpx.Request] = []
    responses = [
        {
            "items": [
                {
                    "entity": "entry",
                    "collectionTitle": "Shared",
                    "entryId": "dataset-1",
                    "workbookId": None,
                    "collectionId": "collection-1",
                    "scope": "dataset",
                    "type": "dataset",
                    "displayKey": None,
                    "key": None,
                    "isDelegated": True,
                }
            ],
            "nextPageToken": "1",
        },
        {
            "items": [
                {
                    "entity": "workbook",
                    "collectionTitle": "Shared",
                    "title": "Reports",
                    "workbookId": "workbook-1",
                    "collectionId": "collection-1",
                    "isDelegated": False,
                }
            ]
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=responses.pop(0))

    with DataLensClientYC(auth=None, transport=httpx.MockTransport(handler)) as client:
        items = list(client.shared_entries.list(entry_id="connection-1", entry_as="source"))
    assert isinstance(items[0], SharedEntryBindingEntry)
    assert isinstance(items[1], SharedEntryBindingWorkbook)
    assert items[0].permissions is None
    assert items[1].permissions is None
    assert [json.loads(request.content)["page"] for request in requests] == [0, 1]
    assert all(request.url.path == "/rpc/getSharedEntryBindings" for request in requests)


@pytest.mark.parametrize("installation", ["yacloud", "enterprise"])
def test_shared_binding_listing_exposes_typed_permissions(installation: str) -> None:
    response = {
        "items": [
            {
                "entity": "entry",
                "collectionTitle": "Shared",
                "entryId": "dataset-1",
                "workbookId": None,
                "collectionId": "collection-1",
                "scope": "dataset",
                "type": "dataset",
                "displayKey": None,
                "key": None,
                "isDelegated": True,
                "permissions": {
                    "copy": True,
                    "createEntryBinding": True,
                    "createLimitedEntryBinding": False,
                    "delete": False,
                    "limitedView": True,
                    "listAccessBindings": True,
                    "move": False,
                    "securityApprove": False,
                    "update": True,
                    "updateAccessBindings": False,
                    "view": True,
                },
            },
            {
                "entity": "workbook",
                "collectionTitle": "Shared",
                "title": "Reports",
                "workbookId": "workbook-1",
                "collectionId": "collection-1",
                "isDelegated": False,
                "permissions": {
                    "copy": False,
                    "delete": False,
                    "embed": True,
                    "limitedView": False,
                    "listAccessBindings": True,
                    "move": False,
                    "publish": True,
                    "update": True,
                    "updateAccessBindings": False,
                    "view": True,
                },
            },
        ]
    }
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=response))
    client: DataLensClientEnterprise | DataLensClientYC
    if installation == "enterprise":
        client = DataLensClientEnterprise(base_url="https://enterprise.example.test", auth=None, transport=transport)
    else:
        client = DataLensClientYC(auth=None, transport=transport)

    with client:
        items = list(
            client.shared_entries.list(entry_id="connection-1", entry_as="source", include_permissions_info=True)
        )

    assert isinstance(items[0], SharedEntryBindingEntry)
    assert isinstance(items[0].permissions, SharedEntryBindingEntryPermissions)
    assert items[0].permissions.can_copy is True
    assert items[0].permissions.create_entry_binding is True
    assert isinstance(items[1], SharedEntryBindingWorkbook)
    assert isinstance(items[1].permissions, SharedEntryBindingWorkbookPermissions)
    assert items[1].permissions.can_copy is False
    assert items[1].permissions.publish is True


@pytest.mark.parametrize(
    ("domain_type", "dto_type"),
    [
        (SharedEntryBindingEntryPermissions, dto.SharedEntryBindingEntryPermissionsReadDTO),
        (SharedEntryBindingWorkbookPermissions, dto.WorkbookPermissionsReadDTO),
    ],
)
def test_shared_binding_permission_types_match_generated_contract(domain_type: type, dto_type: type[BaseModel]) -> None:
    domain_fields = get_type_hints(domain_type)
    generated_fields = {name: field.annotation for name, field in dto_type.model_fields.items()}

    assert {field.name for field in fields(domain_type)} == set(generated_fields)
    assert domain_fields == generated_fields
    assert "copy" not in domain_fields


def test_shared_binding_rejects_non_boolean_delegation() -> None:
    with (
        DataLensClientYC(auth=None, transport=httpx.MockTransport(lambda _: httpx.Response(500))) as client,
        pytest.raises(DTOValidationError),
    ):
        client.shared_entries.bind(source_id="x", target_id="y", delegation="yes")  # type: ignore[arg-type]


def test_shared_binding_dto_fields_follow_spec() -> None:
    spec = json.loads((Path(__file__).parents[1] / "spec" / "yacloud.json").read_text())
    spec["components"]["schemas"]["SharedEntryBindingArgs"]["properties"]["futureFlag"] = {"type": "boolean"}
    config = next(item for item in codegen.RPC_NAMESPACE_CONFIGS if item["namespace"] == "shared_entries")
    contract = codegen.build_rpc_namespace_contract_meta(spec, config=config)
    assert contract is not None
    source = codegen._emit_rpc_namespace_dto({"installations": {}, "rpc_namespaces": {"shared_entries": contract}})
    assert "future_flag: bool" in source


def test_enterprise_exposes_shared_bindings() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"sourceId": "dataset-1", "targetId": "workbook-1", "isDelegated": False})

    with DataLensClientEnterprise(
        base_url="https://enterprise.example.test", auth=None, transport=httpx.MockTransport(handler)
    ) as client:
        binding = client.shared_entries.get_delegation(source_id="dataset-1", target_id="workbook-1")

    assert binding.is_delegated is False
    assert requests[0].url.path == "/rpc/getSharedEntryDelegation"
