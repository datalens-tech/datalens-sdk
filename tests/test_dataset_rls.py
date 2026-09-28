from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from typing import cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk.converter.dataset import DatasetConverter
from datalens_sdk.domain.dataset_rls import RLSAdd, RLSClear, RLSDelete, RLSUpdate

ClientType = type[dl.DataLensClientYC] | type[dl.DataLensClientEnterprise]


def _entry(
    value: str | None, *, subject_id: str = "reader", subject_type: str = "user", pattern: str = "value"
) -> dict[str, object]:
    entry: dict[str, object] = {
        "field_guid": "shop-guid",
        "subject": {"subject_id": subject_id, "subject_type": subject_type},
        "pattern_type": pattern,
    }
    if value is not None:
        entry["allowed_value"] = value
    return entry


def _state() -> dict[str, object]:
    return {
        "result_schema": [
            {
                "guid": "shop-guid",
                "name": "shop_name",
                "title": "Shop",
                "source": "shop_column",
                "calc_mode": "direct",
                "type": "DIMENSION",
            },
            {"guid": "region-guid", "name": "region", "title": "Region", "calc_mode": "direct", "type": "DIMENSION"},
        ],
        "rls2": {"shop-guid": [_entry("Epsilon")], "region-guid": [{**_entry("North"), "field_guid": "region-guid"}]},
    }


class Harness:
    def __init__(
        self,
        client_type: ClientType,
        *,
        state: dict[str, object] | None = None,
        validated: dict[str, object] | None = None,
    ) -> None:
        self.state = deepcopy(state if state is not None else _state())
        self.validated = validated
        self.requests: list[httpx.Request] = []
        self.client = client_type(auth=None, base_url="http://test", transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/rpc/getDataset":
            content = self.state
        elif request.url.path == "/rpc/validateDataset":
            content = self.validated if self.validated is not None else self.state
        else:
            payload = json.loads(request.content)
            if request.url.path == "/rpc/updateDataset":
                content = payload["data"]["dataset"]
            else:
                assert request.url.path == "/rpc/createDataset"
                content = payload["dataset"]
        return httpx.Response(200, json={"id": "dataset-1", "name": "Shops", "dataset": content})

    @property
    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]

    def dataset(self) -> dl.Dataset:
        return self.client.get.dataset(by_id="dataset-1")


@pytest.fixture(params=[dl.DataLensClientYC, dl.DataLensClientEnterprise])
def client_type(request: pytest.FixtureRequest) -> ClientType:
    return cast(ClientType, request.param)


@pytest.mark.parametrize("field", ["shop-guid", "shop_name", "Shop", "shop_column"])
def test_rls_resolves_aliases_and_preserves_operation_order(client_type: ClientType, field: str) -> None:
    harness = Harness(client_type)
    dataset = harness.dataset()
    original = deepcopy(dataset.raw)
    updated = (
        dataset.update.add_rls(field="shop-guid", subject_id="reader", allowed_value="discarded")
        .delete_rls(field=field)
        .add_rls(field=dataset.fields.by_guid("shop-guid"), subject_id="reader", allowed_value="Delta")
        .add_rls(field=field, subject_id="reader", allowed_value="Gamma")
        .execute()
    )
    assert updated.rls2 == {
        **cast(dict[str, object], harness.state["rls2"]),
        "shop-guid": [_entry("Delta"), _entry("Gamma")],
    }
    assert harness.paths == ["/rpc/getDataset", "/rpc/updateDataset"]
    assert dataset.raw == original


@pytest.mark.parametrize("field", ["shop-guid", "shop_name", "Shop", "shop_column"])
def test_rls_update_replaces_all_patterns_for_only_the_matching_subject(client_type: ClientType, field: str) -> None:
    state = _state()
    neighbors = [_entry("other-user", subject_id="another"), _entry("group", subject_type="group")]
    cast(dict[str, object], state["rls2"])["shop-guid"] = [
        _entry("Epsilon"),
        _entry("Gamma"),
        _entry(None, pattern="all"),
        _entry(None, pattern="userid"),
        *neighbors,
    ]
    harness = Harness(client_type, state=state)
    result = (
        harness.dataset()
        .update.update_rls(field=field, subject_id="reader", subject_name="Renamed reader", allowed_value="Delta")
        .execute()
    )
    expected = _entry("Delta")
    cast(dict[str, object], expected["subject"])["subject_name"] = "Renamed reader"
    assert result.rls2 == {**cast(dict[str, object], state["rls2"]), "shop-guid": [*neighbors, expected]}


@pytest.mark.parametrize(
    ("operations", "values"),
    [
        (("add", "update"), ["update"]),
        (("update", "add"), ["update", "add"]),
        (("update", "update"), ["update"]),
        (("delete", "update"), ["update"]),
        (("update", "delete", "add"), ["add"]),
        (("clear", "update", "add"), ["update", "add"]),
        (("update", "clear", "update"), ["update"]),
        (("update", "clear", "clear"), []),
    ],
)
def test_rls_subject_replacement_composes_with_other_operations(
    client_type: ClientType, operations: tuple[str, ...], values: list[str]
) -> None:
    harness = Harness(client_type)
    update = harness.dataset().update
    for operation in operations:
        if operation == "add":
            update.add_rls(field="Shop", subject_id="reader", allowed_value="add")
        elif operation == "update":
            update.update_rls(field="shop-guid", subject_id="reader", allowed_value="update")
        elif operation == "delete":
            update.delete_rls(field="shop_name")
        else:
            update.clear_rls()
    result = update.execute()
    expected = {} if "clear" in operations else dict(cast(dict[str, object], harness.state["rls2"]))
    if values:
        expected["shop-guid"] = [_entry(value) for value in values]
    assert result.rls2 == expected
    assert harness.paths.count("/rpc/updateDataset") == 1


@pytest.mark.parametrize("pattern", ["value", "all", "userid"])
def test_rls_update_inserts_absent_subject_and_handles_pattern_changes(
    client_type: ClientType, pattern: dl.RLSPatternType
) -> None:
    harness = Harness(client_type)
    dataset = harness.dataset()
    result = dataset.update.update_rls(field="Shop", subject_id="new-reader", pattern_type=pattern).execute()
    assert result.rls2["shop-guid"] == [_entry("Epsilon"), _entry(None, subject_id="new-reader", pattern=pattern)]
    result = dataset.update.update_rls(field="Shop", subject_id="reader", pattern_type=pattern).execute()
    assert result.rls2["shop-guid"] == [_entry(None, pattern=pattern)]


@pytest.mark.parametrize("operation", ["add", "update", "delete"])
@pytest.mark.parametrize("bad_field", ["typo", "", "00000000-0000-0000-0000-000000000000"])
def test_rls_rejects_unknown_fields_before_save(client_type: ClientType, operation: str, bad_field: str) -> None:
    harness = Harness(client_type)
    update = harness.dataset().update
    if operation == "add":
        update.add_rls(field=bad_field, subject_id="reader")
    elif operation == "update":
        update.update_rls(field=bad_field, subject_id="reader")
    else:
        update.delete_rls(field=bad_field)
    with pytest.raises(dl.DataLensValidationError, match=r"not found|empty"):
        update.execute()
    assert harness.paths == ["/rpc/getDataset"]


@pytest.mark.parametrize("attribute", ["title", "name", "source"])
def test_rls_rejects_ambiguous_aliases_but_prefers_exact_guid(client_type: ClientType, attribute: str) -> None:
    state = _state()
    schema = cast(list[dict[str, object]], state["result_schema"])
    for field in schema:
        field[attribute] = "duplicate"
    harness = Harness(client_type, state=state)
    dataset = harness.dataset()
    with pytest.raises(dl.DataLensValidationError, match="ambiguous"):
        dataset.update.delete_rls(field="duplicate").execute()
    assert harness.paths == ["/rpc/getDataset"]
    result = dataset.update.delete_rls(field="shop-guid").execute()
    assert set(result.rls2) == {"region-guid"}
    schema[1][attribute] = "shop-guid"
    harness = Harness(client_type, state=state)
    result = harness.dataset().update.delete_rls(field="shop-guid").execute()
    assert set(result.rls2) == {"region-guid"}


def test_rls_dataset_field_requires_membership_and_never_falls_back_to_title(client_type: ClientType) -> None:
    harness = Harness(client_type)
    dataset = harness.dataset()
    field = dataset.fields.by_guid("shop-guid")
    with pytest.raises(dl.DataLensValidationError, match="another dataset"):
        dataset.update.add_rls(field=replace(field, dataset_id="foreign"), subject_id="reader")
    with pytest.raises(dl.DataLensValidationError, match="not found"):
        dataset.update.delete_rls(field=replace(field, guid="Shop")).execute()
    assert harness.paths == ["/rpc/getDataset"]


@pytest.mark.parametrize("subject_type", [None, "unknown", "notfound"])
def test_rls_update_rejects_unresolved_saved_subject_type(client_type: ClientType, subject_type: str | None) -> None:
    state = _state()
    entry = _entry("Epsilon")
    subject = cast(dict[str, object], entry["subject"])
    if subject_type is None:
        subject.pop("subject_type")
    else:
        subject["subject_type"] = subject_type
    cast(dict[str, object], state["rls2"])["shop-guid"] = [entry]
    harness = Harness(client_type, state=state)
    with pytest.raises(dl.DataLensValidationError, match="missing or unresolved"):
        harness.dataset().update.update_rls(field="Shop", subject_id="reader", allowed_value="Delta").execute()
    assert harness.paths == ["/rpc/getDataset"]


def test_rls_changes_are_complete_immutable_and_replayable(client_type: ClientType) -> None:
    harness = Harness(client_type)
    dataset = harness.dataset()
    update = dataset.update.delete_rls(field="Shop").add_rls(
        field="shop-guid", subject_id="reader", allowed_value="Delta"
    )
    changes = update.rls2_changes
    spec = update.to_spec()
    assert isinstance(changes[0], RLSDelete)
    assert isinstance(changes[1], RLSAdd)
    with pytest.raises(FrozenInstanceError):
        changes[1].rule.allowed_value = "changed"  # type: ignore[misc]
    update.clear_rls().update_rls(field="shop-guid", subject_id="reader", allowed_value="last")
    assert isinstance(update.rls2_changes[0], RLSClear)
    assert isinstance(update.rls2_changes[1], RLSUpdate)
    assert spec.rls2_changes == changes
    assert len(changes) == 2
    replayed = DatasetConverter.apply_rls2_changes(harness.state, changes)
    assert cast(dict[str, object], replayed["rls2"])["shop-guid"] == [_entry("Delta")]
    assert update.execute().rls2 == DatasetConverter.apply_rls2_changes(harness.state, update.rls2_changes)["rls2"]
    assert harness.state == _state()


@pytest.mark.parametrize("field", ["new-guid", "New field"])
@pytest.mark.parametrize("create", [False, True])
def test_rls_resolves_new_fields_against_validated_schema(client_type: ClientType, field: str, create: bool) -> None:
    validated = _state()
    cast(list[dict[str, object]], validated["result_schema"]).append(
        {"guid": "new-guid", "title": "New field", "calc_mode": "formula", "type": "DIMENSION"}
    )
    harness = Harness(client_type, validated=validated)
    if create:
        result = (
            harness.client.create.dataset(name="New", location=dl.EntryLocation.path("/Users/me"))
            .add_calculation(name="New field", guid="new-guid", formula="'new'", kind="DIMENSION")
            .add_rls(field=field, subject_id="reader", allowed_value="new")
            .build()
        )
    else:
        result = (
            harness.dataset()
            .update.add_calculation(name="New field", guid="new-guid", formula="'new'", kind="DIMENSION")
            .add_rls(field=field, subject_id="reader", allowed_value="new")
            .execute()
        )
    assert result.rls2["new-guid"] == [{**_entry("new"), "field_guid": "new-guid"}]
    assert harness.paths[-2:] == ["/rpc/validateDataset", "/rpc/createDataset" if create else "/rpc/updateDataset"]


def test_rls_update_uses_server_rules_and_rejects_fields_removed_by_validation(client_type: ClientType) -> None:
    validated = _state()
    cast(dict[str, object], validated["rls2"])["shop-guid"] = [
        _entry("server-only"),
        _entry("preserved", subject_id="another"),
    ]
    harness = Harness(client_type, validated=validated)
    result = (
        harness.dataset()
        .update.description("Changed")
        .update_rls(field="Shop", subject_id="reader", allowed_value="Delta")
        .execute()
    )
    assert result.rls2["shop-guid"] == [_entry("preserved", subject_id="another"), _entry("Delta")]
    validated["result_schema"] = []
    harness = Harness(client_type, validated=validated)
    with pytest.raises(dl.DataLensValidationError, match="not found"):
        harness.dataset().update.description("Changed").delete_rls(field="Shop").execute()
    assert harness.paths == ["/rpc/getDataset", "/rpc/validateDataset"]


def test_rls_rejects_create_without_matching_schema(client_type: ClientType) -> None:
    harness = Harness(client_type)
    with pytest.raises(dl.DataLensValidationError, match="not found"):
        harness.client.create.dataset(name="New", location=dl.EntryLocation.path("/Users/me")).add_rls(
            field="typo", subject_id="reader"
        ).build()
    assert harness.paths == []


def test_rls_clear_discards_unresolved_queued_references(client_type: ClientType) -> None:
    harness = Harness(client_type)
    update = harness.dataset().update.add_rls(field="discarded-typo", subject_id="reader")
    snapshot = update.rls2_changes
    result = update.clear_rls().execute()
    assert result.rls2 == {}
    assert isinstance(snapshot[0], RLSAdd)
    assert update.rls2_changes == (RLSClear(),)


def test_rls_saved_guid_does_not_rebind_to_another_fields_title(client_type: ClientType) -> None:
    validated = _state()
    validated["result_schema"] = [{"guid": "different-guid", "title": "shop-guid"}]
    harness = Harness(client_type, validated=validated)
    dataset = harness.dataset()
    with pytest.raises(dl.DataLensValidationError, match="not found"):
        dataset.update.delete_field(field="shop-guid").add_rls(field="shop-guid", subject_id="reader").execute()
    assert harness.paths == ["/rpc/getDataset", "/rpc/validateDataset"]
