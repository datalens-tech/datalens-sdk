from __future__ import annotations

from collections.abc import Mapping

import httpx
import pytest

from datalens_sdk import DataLensClientYC
from datalens_sdk.errors import DTOValidationError


def _cluster_response() -> dict[str, object]:
    return {
        "id": "trino-1",
        "clusterId": "managed-2",
        "collectionId": "collection-1",
        "cloudEnvironmentId": "env-1",
        "name": "Analytics",
        "description": "A cluster",
        "labels": {"team": "analytics"},
        "config": {
            "trinoVersion": "476",
            "catalogsConfig": [{"catalogId": "catalog-1"}],
            "coordinatorConfig": {"resources": {"resourcePresetId": "coordinator-preset"}},
            "workerConfig": {
                "resources": {"resourcePresetId": "worker-preset"},
                "scalePolicy": {"scaleType": "autoScale", "autoScale": {"minCount": "0", "maxCount": "64"}},
            },
        },
        "health": "ALIVE",
        "status": "RUNNING",
        "coordinatorUrl": "",
        "entryId": "",
    }


def _client_for(response: Mapping[str, object]) -> DataLensClientYC:
    return DataLensClientYC(
        auth=None,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response)),
    )


def test_trino_get_rejects_python_field_name_instead_of_required_wire_alias() -> None:
    malformed = _cluster_response()
    malformed["cluster_id"] = malformed.pop("clusterId")
    client = _client_for(malformed)

    with (
        client,
        pytest.raises(DTOValidationError, match=r"(?s)getTrinoCluster.*clusterId"),
    ):
        client.get.trino_cluster(by_id="trino-1")


def test_trino_get_rejects_python_field_name_in_nested_config() -> None:
    malformed = _cluster_response()
    config = malformed["config"]
    assert isinstance(config, dict)
    worker = config["workerConfig"]
    assert isinstance(worker, dict)
    scale_policy = worker["scalePolicy"]
    assert isinstance(scale_policy, dict)
    auto_scale = scale_policy["autoScale"]
    assert isinstance(auto_scale, dict)
    auto_scale["min_count"] = auto_scale.pop("minCount")
    client = _client_for(malformed)

    with (
        client,
        pytest.raises(DTOValidationError, match=r"(?s)getTrinoCluster.*minCount"),
    ):
        client.get.trino_cluster(by_id="trino-1")


def test_trino_cluster_list_rejects_python_page_token_instead_of_wire_alias() -> None:
    malformed = {"clusters": [], "next_page_token": ""}
    client = _client_for(malformed)

    with (
        client,
        pytest.raises(DTOValidationError, match=r"(?s)listTrinoClusters.*nextPageToken"),
    ):
        list(client.list.trino_clusters().pages())


def test_trino_resource_preset_list_rejects_python_page_token_instead_of_wire_alias() -> None:
    malformed = {"resourcePresets": [], "next_page_token": ""}
    client = _client_for(malformed)

    with (
        client,
        pytest.raises(DTOValidationError, match=r"(?s)listTrinoResourcePresets.*nextPageToken"),
    ):
        list(client.list.trino_resource_presets(cloud_environment_id="env-1").pages())


def test_trino_get_keeps_forward_compatible_unknown_response_fields() -> None:
    response = _cluster_response()
    response["futureField"] = {"nested": True}
    config = response["config"]
    assert isinstance(config, dict)
    worker = config["workerConfig"]
    assert isinstance(worker, dict)
    worker["futureNestedField"] = {"future": True}
    client = _client_for(response)

    with client:
        cluster = client.get.trino_cluster(by_id="trino-1")

    assert cluster.id == "trino-1"
    assert cluster.raw["futureField"] == {"nested": True}
    assert cluster.raw == response
