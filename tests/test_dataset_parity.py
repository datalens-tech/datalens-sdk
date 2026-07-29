from __future__ import annotations

import json
from typing import cast

import httpx
import pytest

import datalens_sdk as dl
from datalens_sdk import JoinCondition
from datalens_sdk.converter.dataset import DatasetConverter
from datalens_sdk.domain.dataset import Dataset, Source, SourcesProxy
from datalens_sdk.domain.dataset_update import DatasetUpdate
from datalens_sdk.errors import DatalensValidationError

_RLS2_FIELD = "rls2"


class RecordedTransport:
    def __init__(self, routes: dict[str, list[httpx.Response] | httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._routes = {
            path: list(response) if isinstance(response, list) else [response] for path, response in routes.items()
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        responses = self._routes.get(request.url.path)
        if not responses:
            return httpx.Response(404, json={"code": "NOT_FOUND", "message": f"Unexpected {request.url.path}"})
        response = responses.pop(0)
        response.request = request
        return response

    def request_json(self, index: int) -> dict[str, object]:
        data: object = json.loads(self.requests[index].content.decode())
        assert isinstance(data, dict)
        return cast(dict[str, object], data)


def _dataset_payload(*, description: str = "Base") -> dict[str, object]:
    return {
        "id": "ds-1",
        "name": "Sales",
        "dataset": {
            "description": description,
            "sources": [
                {
                    "id": "src-1",
                    "title": "orders",
                    "source_type": "PG_TABLE",
                    "connection_id": "conn-1",
                    "connection_type": "postgres",
                    "parameters": {"schema_name": "public", "table_name": "orders"},
                    "raw_schema": [
                        {
                            "guid": "src-date",
                            "title": "Order Date",
                            "name": "order_date",
                            "calc_mode": "direct",
                            "data_type": "date",
                            "type": "DIMENSION",
                        }
                    ],
                }
            ],
            "source_avatars": [{"id": "src-1", "source_id": "src-1", "title": "orders", "is_root": True}],
            "avatar_relations": [],
            "result_schema": [
                {
                    "guid": "date",
                    "title": "Order Date",
                    "name": "order_date",
                    "calc_mode": "direct",
                    "data_type": "date",
                    "cast": "date",
                    "source": "order_date",
                    "avatar_id": "src-1",
                    "type": "DIMENSION",
                },
                {
                    "guid": "sales",
                    "title": "Sales",
                    "name": "sales",
                    "calc_mode": "direct",
                    "data_type": "float",
                    "cast": "float",
                    "source": "sales",
                    "avatar_id": "src-1",
                    "type": "MEASURE",
                    "aggregation": "sum",
                },
                {
                    "guid": "scale",
                    "title": "Scale",
                    "calc_mode": "parameter",
                    "cast": "integer",
                    "default_value": 1,
                },
            ],
            "obligatory_filters": [],
            _RLS2_FIELD: {},
        },
    }


def test_dataset_read_model_exposes_fields_sources_parameters_and_rls2() -> None:
    recorder = RecordedTransport({"/rpc/getDataset": httpx.Response(200, json=_dataset_payload())})
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    dataset = client.get.dataset(by_id="ds-1")

    assert len(dataset.fields) == 3
    assert dataset.fields.by_name("Sales").guid == "sales"
    assert dataset.fields.by_guid("date").name == "order_date"
    assert dataset.parameters.by_name("Scale").default_value == 1
    assert dataset.sources.by_alias("orders").fields.by_name("Order Date").name == "order_date"
    assert dataset.rls2 == {}


def test_dataset_update_actions_validate_then_save_server_state_with_rls2() -> None:
    validated = _dataset_payload(description="Validated")
    validated_dataset = cast(dict[str, object], validated["dataset"])
    validated_schema = cast(list[dict[str, object]], validated_dataset["result_schema"])
    validated_schema.append(
        {
            "guid": "calc-1",
            "title": "Sales Plus",
            "calc_mode": "formula",
            "formula": "[Sales] + 1",
            "data_type": "float",
            "type": "MEASURE",
            "aggregation": "sum",
        }
    )
    validated_dataset["obligatory_filters"] = [
        {
            "id": "filter-1",
            "field_guid": "date",
            "default_filters": [{"column": "date", "operation": "EQ", "values": ["2026-06-30"]}],
        }
    ]
    saved = {**validated, "dataset": {**validated_dataset, "description": "Saved"}}
    recorder = RecordedTransport(
        {
            "/rpc/getDataset": httpx.Response(200, json=_dataset_payload()),
            "/rpc/validateDataset": httpx.Response(200, json=validated),
            "/rpc/updateDataset": httpx.Response(200, json=saved),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    dataset = client.get.dataset(by_id="ds-1")
    updated = (
        dataset.update.description("Validated")
        .add_calculation(name="Sales Plus", formula="[Sales] + 1", kind="MEASURE", aggregation="sum")
        .change_field_type(field=dataset.fields.by_name("Order Date"), to="string")
        .add_default_filter(field=dataset.fields.by_name("Order Date"), operator="EQ", values=["2026-06-30"])
        .add_rls(
            field=dataset.fields.by_name("Order Date"),
            subject_id="user-1",
            allowed_value="2026-06-30",
            subject_type="user",
        )
        .execute()
    )

    assert [request.url.path for request in recorder.requests] == [
        "/rpc/getDataset",
        "/rpc/validateDataset",
        "/rpc/updateDataset",
    ]
    validate_payload = recorder.request_json(1)
    updates = cast(list[dict[str, object]], cast(dict[str, object], validate_payload["data"])["updates"])
    assert [update["action"] for update in updates] == [
        "update_description",
        "add_field",
        "update_field",
        "add_obligatory_filter",
    ]
    update_payload = recorder.request_json(2)
    saved_dataset = cast(dict[str, object], cast(dict[str, object], update_payload["data"])["dataset"])
    assert saved_dataset["description"] == "Validated"
    assert cast(dict[str, object], saved_dataset["rls2"]) == {
        "date": [
            {
                "subject": {"subject_id": "user-1", "subject_type": "user"},
                "allowed_value": "2026-06-30",
                "field_guid": "date",
                "pattern_type": "value",
            }
        ]
    }
    assert updated.fields.by_name("Sales Plus").formula == "[Sales] + 1"


def test_dataset_read_and_update_keep_only_rls2_from_backend_state() -> None:
    unsupported_field = _RLS2_FIELD.removesuffix("2")
    backend_payload = _dataset_payload()
    backend_dataset = cast(dict[str, object], backend_payload["dataset"])
    backend_dataset[unsupported_field] = {"date": ["user-1"]}
    recorder = RecordedTransport(
        {
            "/rpc/getDataset": httpx.Response(200, json=backend_payload),
            "/rpc/validateDataset": httpx.Response(200, json=backend_payload),
            "/rpc/updateDataset": httpx.Response(200, json=backend_payload),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    dataset = client.get.dataset(by_id="ds-1")
    raw_dataset = cast(dict[str, object], dataset.raw["dataset"])
    assert {key for key in raw_dataset if key.startswith(_RLS2_FIELD.removesuffix("2"))} == {_RLS2_FIELD}

    updated = dataset.update.description("Updated").execute()

    for request_index in (1, 2):
        request_data = cast(dict[str, object], recorder.request_json(request_index)["data"])
        request_dataset = cast(dict[str, object], request_data["dataset"])
        assert {key for key in request_dataset if key.startswith(_RLS2_FIELD.removesuffix("2"))} == {_RLS2_FIELD}
    updated_raw_dataset = cast(dict[str, object], updated.raw["dataset"])
    assert {key for key in updated_raw_dataset if key.startswith(_RLS2_FIELD.removesuffix("2"))} == {_RLS2_FIELD}


def test_dataset_create_stages_supported_mutations_before_single_create() -> None:
    validated_state: dict[str, object] = {
        "description": "Server description",
        "sources": [],
        "source_avatars": [],
        "avatar_relations": [],
        "result_schema": [
            {
                "guid": "calc-1",
                "title": "Constant",
                "calc_mode": "formula",
                "formula": "1",
                "type": "MEASURE",
                "aggregation": "sum",
            }
        ],
        "obligatory_filters": [
            {
                "id": "filter-1",
                "field_guid": "calc-1",
                "default_filters": [{"column": "calc-1", "operation": "EQ", "values": [1]}],
            }
        ],
        _RLS2_FIELD: {},
        "load_preview_by_default": False,
        "cache_invalidation_source": {
            "mode": "sql",
            "sql": "SELECT 1",
            "filters": [],
        },
    }
    recorder = RecordedTransport(
        {
            "/rpc/validateDataset": httpx.Response(200, json={"dataset": validated_state}),
            "/rpc/createDataset": httpx.Response(
                200,
                json={"id": "ds-created", "name": "Created with updates", "dataset": validated_state},
            ),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    created = (
        client.create.dataset(name="Created with updates", location=dl.EntryLocation.path("/Users/me"))
        .description("Creation description")
        .add_calculation(
            name="Constant",
            formula="1",
            kind="MEASURE",
            aggregation="sum",
            guid="calc-1",
        )
        .clone_field(field="calc-1", new_title="Constant copy", new_guid="calc-copy")
        .add_default_filter(field="calc-1", operator="EQ", values=[1])
        .add_rls(field="calc-1", subject_id="user-1", allowed_value="1")
        .update_setting(name="load_preview_by_default", value=False)
        .update_cache_invalidation_source(source=dl.CacheInvalidationSource(mode="sql", sql="SELECT 1"))
        .build()
    )

    assert created.id == "ds-created"
    assert [request.url.path for request in recorder.requests] == [
        "/rpc/validateDataset",
        "/rpc/createDataset",
    ]
    validate_payload = recorder.request_json(0)
    validate_data = cast(dict[str, object], validate_payload["data"])
    validate_dataset = cast(dict[str, object], validate_data["dataset"])
    assert {key for key in validate_dataset if key.startswith(_RLS2_FIELD.removesuffix("2"))} <= {_RLS2_FIELD}
    updates = cast(list[dict[str, object]], validate_data["updates"])
    assert [update["action"] for update in updates] == [
        "add_field",
        "clone_field",
        "add_obligatory_filter",
        "update_setting",
        "update_cache_invalidation_source",
    ]
    assert updates[1]["field"] == {
        "from_guid": "calc-1",
        "guid": "calc-copy",
        "title": "Constant copy",
    }
    create_payload = recorder.request_json(1)
    dataset_content = cast(dict[str, object], create_payload["dataset"])
    assert dataset_content["description"] == "Creation description"
    assert {key for key in dataset_content if key.startswith(_RLS2_FIELD.removesuffix("2"))} == {_RLS2_FIELD}
    assert cast(dict[str, object], dataset_content["rls2"])["calc-1"] == [
        {
            "subject": {"subject_id": "user-1", "subject_type": "user"},
            "allowed_value": "1",
            "field_guid": "calc-1",
            "pattern_type": "value",
        }
    ]


def test_apply_rls2_changes_keeps_only_the_supported_rls_field() -> None:
    unsupported_field = _RLS2_FIELD.removesuffix("2")
    state = DatasetConverter.apply_rls2_changes(
        {unsupported_field: {"calc-1": ["user-1"]}},
        {"calc-1": [{"field_guid": "calc-1"}]},
    )

    assert state == {_RLS2_FIELD: {"calc-1": [{"field_guid": "calc-1"}]}}


def test_dataset_create_places_mutations_after_source_graph_actions() -> None:
    source = Source(
        id="src-new",
        source_type="PG_TABLE",
        title="orders",
        connection_id="conn-1",
        connection_type="postgres",
        parameters={"schema_name": "public", "table_name": "orders"},
    )
    mutations = DatasetUpdate(dataset=Dataset(id=None))
    mutations.update_setting(name="template_enabled", value=True)

    payload = DatasetConverter.from_domain_create_validate_step(
        sources=[source],
        relations=[],
        refresh_sources=True,
        actions=mutations.actions,
    )

    updates = cast(list[dict[str, object]], cast(dict[str, object], payload["data"])["updates"])
    assert [update["action"] for update in updates] == [
        "add_source",
        "add_source_avatar",
        "refresh_source",
        "update_setting",
    ]


def test_dataset_update_resolves_default_filter_string_field_to_guid() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getDataset": httpx.Response(200, json=_dataset_payload()),
            "/rpc/validateDataset": httpx.Response(200, json=_dataset_payload()),
            "/rpc/updateDataset": httpx.Response(200, json=_dataset_payload()),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    (
        client.get.dataset(by_id="ds-1")
        .update.add_default_filter(field="Order Date", operator="EQ", values=["2026-06-30"])
        .execute()
    )

    validate_payload = recorder.request_json(1)
    updates = cast(list[dict[str, object]], cast(dict[str, object], validate_payload["data"])["updates"])
    default_filter = cast(dict[str, object], updates[0]["obligatory_filter"])
    assert default_filter["field_guid"] == "date"
    assert cast(list[dict[str, object]], default_filter["default_filters"])[0]["column"] == "date"


def test_dataset_enrich_via_refresh_uses_validate_actions() -> None:
    refreshed = _dataset_payload(description="Refreshed")
    refreshed_dataset = cast(dict[str, object], refreshed["dataset"])
    refreshed_schema = cast(list[dict[str, object]], refreshed_dataset["result_schema"])
    refreshed_schema.append(
        {
            "guid": "new-col",
            "title": "New Column",
            "name": "new_col",
            "calc_mode": "direct",
            "data_type": "string",
            "type": "DIMENSION",
        }
    )
    recorder = RecordedTransport(
        {
            "/rpc/getDataset": httpx.Response(200, json=_dataset_payload()),
            "/rpc/validateDataset": httpx.Response(200, json=refreshed),
            "/rpc/updateDataset": httpx.Response(200, json=refreshed),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    updated = client.get.dataset(by_id="ds-1").enrich_via_refresh()

    validate_payload = recorder.request_json(1)
    updates = cast(list[dict[str, object]], cast(dict[str, object], validate_payload["data"])["updates"])
    assert updates == [
        {
            "action": "refresh_source",
            "source": {"id": "src-1", "force_update_fields": True},
        }
    ]
    assert updated.fields.by_name("New Column").guid == "new-col"


def test_dataset_enrich_via_refresh_preserves_id_when_update_response_omits_id() -> None:
    refreshed = _dataset_payload(description="Refreshed")
    update_response = dict(refreshed)
    update_response.pop("id")
    recorder = RecordedTransport(
        {
            "/rpc/getDataset": httpx.Response(200, json=_dataset_payload()),
            "/rpc/validateDataset": httpx.Response(200, json=refreshed),
            "/rpc/updateDataset": httpx.Response(200, json=update_response),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    updated = client.get.dataset(by_id="ds-1").enrich_via_refresh()

    assert updated.id == "ds-1"


def test_dataset_update_relation_serializes_gateway_required_fields() -> None:
    recorder = RecordedTransport(
        {
            "/rpc/getDataset": httpx.Response(200, json=_dataset_payload()),
            "/rpc/validateDataset": httpx.Response(200, json=_dataset_payload()),
            "/rpc/updateDataset": httpx.Response(200, json=_dataset_payload()),
        }
    )
    client = dl.DataLensClientYC(auth=None, base_url="http://test", transport=httpx.MockTransport(recorder.handler))

    client.get.dataset(by_id="ds-1").update.add_relation(
        type="left",
        conditions=[JoinCondition(left="order_date", right="sales", operator="eq")],
    ).execute()

    validate_payload = recorder.request_json(1)
    updates = cast(list[dict[str, object]], cast(dict[str, object], validate_payload["data"])["updates"])
    relation = cast(dict[str, object], updates[0]["avatar_relation"])
    assert relation["managed_by"] == "user"
    assert relation["left_avatar_id"] == "src-1"
    assert relation["right_avatar_id"] == "src-1"
    condition = cast(list[dict[str, object]], relation["conditions"])[0]
    assert condition["type"] == "binary"
    assert cast(dict[str, object], condition["left"]) == {"calc_mode": "direct", "source": "order_date"}
    assert cast(dict[str, object], condition["right"]) == {"calc_mode": "direct", "source": "sales"}


def _dataset_for_update() -> Dataset:
    return Dataset(
        id="ds-1",
        installation="yacloud",
        sources=SourcesProxy(
            [
                Source(
                    id="src-1",
                    source_type="PG_TABLE",
                    title="orders",
                    connection_id="conn-1",
                    connection_type="postgres",
                    parameters={"schema_name": "public", "table_name": "orders"},
                    raw_schema=(
                        {
                            "name": "order_date",
                            "title": "Order Date",
                            "user_type": "date",
                            "nullable": False,
                        },
                    ),
                )
            ]
        ),
        source_avatars=({"id": "avatar-1", "source_id": "src-1", "title": "orders", "is_root": True},),
        avatar_relations=(
            {
                "id": "rel-1",
                "join_type": "inner",
                "required": False,
                "managed_by": "user",
                "left_avatar_id": "avatar-1",
                "right_avatar_id": "avatar-1",
                "conditions": [
                    {
                        "left": {"calc_mode": "direct", "source": "order_date"},
                        "operator": "eq",
                        "right": {"calc_mode": "direct", "source": "order_date"},
                        "type": "binary",
                    }
                ],
            },
        ),
        result_schema=(
            {
                "guid": "date",
                "title": "Order Date",
                "name": "order_date",
                "calc_mode": "direct",
                "source": "order_date",
                "avatar_id": "avatar-1",
            },
            {
                "guid": "sales",
                "title": "Sales",
                "name": "sales",
                "calc_mode": "direct",
                "source": "sales",
                "avatar_id": "avatar-1",
            },
        ),
        obligatory_filters=(
            {
                "id": "filter-1",
                "field_guid": "date",
                "default_filters": [{"column": "date", "operation": "EQ", "values": ["2024-01-01"]}],
            },
        ),
        raw={"dataset": {}},
    )


def test_delete_field_buffers_correct_action() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    upd.delete_field(field="date")
    assert len(upd.actions) == 1
    action = upd.actions[0]
    assert action["action"] == "delete_field"
    field_payload = cast(dict[str, object], action["field"])
    assert field_payload["guid"] == "date"


def test_add_field_buffers_source_avatar() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    upd.add_field(
        title="Order date copy",
        source="order_date",
        kind="DIMENSION",
        avatar_id="avatar-1",
        guid="date-copy",
    )

    action = upd.actions[0]
    assert action["action"] == "add_field"
    field_payload = cast(dict[str, object], action["field"])
    assert field_payload["avatar_id"] == "avatar-1"


def test_clone_field_buffers_correct_action() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    upd.clone_field(field="date", new_title="Date Copy")
    assert len(upd.actions) == 1
    action = upd.actions[0]
    assert action["action"] == "clone_field"
    field_payload = cast(dict[str, object], action["field"])
    assert field_payload == {"from_guid": "date", "title": "Date Copy"}


def test_hide_show_field_sugar() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    upd.hide_field(field="date")
    assert len(upd.actions) == 1
    action = upd.actions[0]
    assert action["action"] == "update_field"
    field_payload = cast(dict[str, object], action["field"])
    assert field_payload["hidden"] is True

    upd2 = DatasetUpdate(dataset=ds)
    upd2.show_field(field="date")
    assert len(upd2.actions) == 1
    action2 = upd2.actions[0]
    assert action2["action"] == "update_field"
    field_payload2 = cast(dict[str, object], action2["field"])
    assert field_payload2["hidden"] is False


def test_update_calculation_buffers_correct_action() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    upd.update_calculation(field="sales", formula="[Sales]*2")
    assert len(upd.actions) == 1
    action = upd.actions[0]
    assert action["action"] == "update_field"
    field_payload = cast(dict[str, object], action["field"])
    assert field_payload["guid"] == "sales"
    assert field_payload["formula"] == "[Sales]*2"


def test_update_parameter_buffers_correct_action() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    upd.update_parameter(field="scale", type="integer", default=10)
    assert len(upd.actions) == 1
    action = upd.actions[0]
    assert action["action"] == "update_field"
    field_payload = cast(dict[str, object], action["field"])
    assert field_payload["guid"] == "scale"
    assert field_payload["cast"] == "integer"
    assert field_payload["default_value"] == 10


def test_update_default_filter_buffers_correct_action() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    upd.update_default_filter(filter_id="filter-1", operator="GT", values=["0"])
    assert len(upd.actions) == 1
    action = upd.actions[0]
    assert action["action"] == "update_obligatory_filter"
    filter_payload = cast(dict[str, object], action["obligatory_filter"])
    assert filter_payload["id"] == "filter-1"
    assert filter_payload["field_guid"] == "date"
    default_filters = cast(list[dict[str, object]], filter_payload["default_filters"])
    assert default_filters[0]["operation"] == "GT"
    assert default_filters[0]["values"] == ["0"]


def test_delete_default_filter_buffers_correct_action() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    upd.delete_default_filter(filter_id="filter-1")
    assert len(upd.actions) == 1
    action = upd.actions[0]
    assert action["action"] == "delete_obligatory_filter"
    filter_payload = cast(dict[str, object], action["obligatory_filter"])
    assert filter_payload["id"] == "filter-1"


def test_update_default_filter_raises_on_unknown_id() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    with pytest.raises(DatalensValidationError, match="not found"):
        upd.update_default_filter(filter_id="bad", operator="GT", values=["0"])


def test_update_relation_buffers_correct_action() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    upd.update_relation(relation_id="rel-1", type="left")
    assert len(upd.actions) == 1
    action = upd.actions[0]
    assert action["action"] == "update_avatar_relation"
    rel_payload = cast(dict[str, object], action["avatar_relation"])
    assert rel_payload["id"] == "rel-1"
    assert rel_payload["join_type"] == "left"
    conditions = cast(list[dict[str, object]], rel_payload["conditions"])
    assert len(conditions) > 0


def test_delete_relation_buffers_correct_action() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    upd.delete_relation(relation_id="rel-1")
    assert len(upd.actions) == 1
    action = upd.actions[0]
    assert action["action"] == "delete_avatar_relation"
    rel_payload = cast(dict[str, object], action["avatar_relation"])
    assert rel_payload["id"] == "rel-1"


def test_update_relation_raises_on_unknown_id() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    with pytest.raises(DatalensValidationError, match="not found"):
        upd.update_relation(relation_id="bad", type="left")


def test_update_relation_raises_on_ambiguous_field_ref() -> None:
    ds_dict = _dataset_for_update()
    ds_with_ambiguous = Dataset(
        id=ds_dict.id,
        installation=ds_dict.installation,
        sources=ds_dict.sources,
        source_avatars=ds_dict.source_avatars,
        avatar_relations=ds_dict.avatar_relations,
        result_schema=(
            {
                "guid": "date",
                "title": "Order Date",
                "name": "order_date",
                "calc_mode": "direct",
                "source": "order_date",
                "avatar_id": "avatar-1",
            },
            {
                "guid": "date2",
                "title": "Order Date 2",
                "name": "order_date",
                "calc_mode": "direct",
                "source": "order_date",
                "avatar_id": "avatar-2",
            },
        ),
        obligatory_filters=ds_dict.obligatory_filters,
        raw=ds_dict.raw,
    )
    upd = DatasetUpdate(dataset=ds_with_ambiguous)
    with pytest.raises(DatalensValidationError, match="ambiguous"):
        upd.update_relation(
            relation_id="rel-1", conditions=[JoinCondition(left="order_date", right="order_date", operator="eq")]
        )


def test_add_source_buffers_correct_action() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    source = Source(
        id="src-2",
        source_type="PG_TABLE",
        title="new_table",
        connection_id="conn-2",
        connection_type="postgres",
        parameters={"table": "new"},
    )
    upd.add_source(source=source)
    assert len(upd.actions) == 1
    action = upd.actions[0]
    assert action["action"] == "add_source"
    src_payload = cast(dict[str, object], action["source"])
    assert src_payload["id"] == "src-2"
    assert src_payload["title"] == "new_table"
    assert src_payload["source_type"] == "PG_TABLE"
    assert src_payload["connection_id"] == "conn-2"


def test_update_source_buffers_correct_action() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    upd.update_source(source_id="src-1", title="new_title")
    assert len(upd.actions) == 1
    action = upd.actions[0]
    assert action["action"] == "update_source"
    src_payload = cast(dict[str, object], action["source"])
    assert src_payload == {
        "id": "src-1",
        "title": "new_title",
        "source_type": "PG_TABLE",
        "connection_id": "conn-1",
        "parameters": {"schema_name": "public", "table_name": "orders"},
        "raw_schema": [
            {
                "name": "order_date",
                "title": "Order Date",
                "user_type": "date",
                "nullable": False,
            }
        ],
    }


def test_update_source_preserves_required_fields_when_updating_parameters() -> None:
    upd = DatasetUpdate(dataset=_dataset_for_update())

    upd.update_source(source_id="src-1", parameters={"table": "updated"})

    action = upd.actions[0]
    assert action["action"] == "update_source"
    source_payload = cast(dict[str, object], action["source"])
    assert source_payload == {
        "id": "src-1",
        "title": "orders",
        "source_type": "PG_TABLE",
        "connection_id": "conn-1",
        "parameters": {"table": "updated"},
        "raw_schema": [
            {
                "name": "order_date",
                "title": "Order Date",
                "user_type": "date",
                "nullable": False,
            }
        ],
    }


def test_delete_source_buffers_correct_action() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    upd.delete_source(source_id="src-1")
    assert len(upd.actions) == 1
    action = upd.actions[0]
    assert action["action"] == "delete_source"
    src_payload = cast(dict[str, object], action["source"])
    assert src_payload["id"] == "src-1"


def test_update_source_avatar_buffers_correct_action() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    upd.update_source_avatar(avatar_id="avatar-1", title="renamed")
    assert len(upd.actions) == 1
    action = upd.actions[0]
    assert action["action"] == "update_source_avatar"
    avatar_payload = cast(dict[str, object], action["source_avatar"])
    assert avatar_payload["id"] == "avatar-1"
    assert avatar_payload["title"] == "renamed"


def test_delete_source_avatar_buffers_correct_action() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    upd.delete_source_avatar(avatar_id="avatar-1")
    assert len(upd.actions) == 1
    action = upd.actions[0]
    assert action["action"] == "delete_source_avatar"
    avatar_payload = cast(dict[str, object], action["source_avatar"])
    assert avatar_payload["id"] == "avatar-1"


def test_replace_connection_buffers_correct_action() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    upd.replace_connection(old_connection_id="conn-1", new_connection_id="conn-2")
    assert len(upd.actions) == 1
    action = upd.actions[0]
    assert action["action"] == "replace_connection"
    conn_payload = cast(dict[str, object], action["connection"])
    assert conn_payload == {"id": "conn-1", "new_id": "conn-2"}


def test_update_setting_buffers_correct_action_bool() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    upd.update_setting(name="load_preview_by_default", value=True)
    assert len(upd.actions) == 1
    action = upd.actions[0]
    assert action["action"] == "update_setting"
    setting_payload = cast(dict[str, object], action["setting"])
    assert setting_payload["name"] == "load_preview_by_default"
    assert setting_payload["value"] is True


def test_update_setting_buffers_correct_action_false() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    upd.update_setting(name="data_export_forbidden", value=False)
    assert len(upd.actions) == 1
    action = upd.actions[0]
    assert action["action"] == "update_setting"
    setting_payload = cast(dict[str, object], action["setting"])
    assert setting_payload["name"] == "data_export_forbidden"
    assert setting_payload["value"] is False


def test_update_cache_invalidation_source_buffers_openapi_action() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    upd.update_cache_invalidation_source(
        source=dl.CacheInvalidationSource(
            mode="formula",
            field=dl.CacheInvalidationField(
                guid="cache-field",
                type="DIMENSION",
                calc_spec=dl.CacheInvalidationFormula(formula="MAX([Order Date])", guid_formula="MAX([date])"),
            ),
            filters=(
                dl.CacheInvalidationFilter(
                    id="cache-filter",
                    field_guid="date",
                    default_filters=(
                        dl.CacheInvalidationFilterCondition(column="date", operation="GTE", values=("2026-01-01",)),
                    ),
                ),
            ),
        )
    )

    assert len(upd.actions) == 1
    action = upd.actions[0]
    assert action["action"] == "update_cache_invalidation_source"
    payload = cast(dict[str, object], action["cache_invalidation_source"])
    assert payload["mode"] == "formula"
    field = cast(dict[str, object], payload["field"])
    assert field["guid"] == "cache-field"
    assert field["calc_spec"] == {"formula": "MAX([Order Date])", "guid_formula": "MAX([date])"}
    filters = cast(list[dict[str, object]], payload["filters"])
    assert filters[0]["field_guid"] == "date"
    assert filters[0]["default_filters"] == [{"column": "date", "operation": "GTE", "values": ["2026-01-01"]}]


def test_chained_methods_return_self() -> None:
    ds = _dataset_for_update()
    upd = DatasetUpdate(dataset=ds)
    result = upd.delete_field(field="date").clone_field(field="sales", new_title="Sales Copy").hide_field(field="sales")
    assert result is upd
    assert len(upd.actions) == 3


def _dataset_with_rich_schema() -> Dataset:
    return Dataset(
        id="ds-rich",
        installation="yacloud",
        sources=SourcesProxy([]),
        result_schema=(
            {
                "guid": "guid-date",
                "title": "Order Date",
                "name": "order_date",
                "calc_mode": "direct",
                "data_type": "date",
                "cast": "date",
                "type": "DIMENSION",
                "hidden": False,
                "description": "Date when order was placed",
            },
            {
                "guid": "guid-revenue",
                "title": "Revenue",
                "name": "revenue",
                "calc_mode": "direct",
                "data_type": "float",
                "cast": "float",
                "type": "MEASURE",
                "aggregation": "sum",
                "hidden": False,
                "description": "Total revenue",
            },
            {
                "guid": "guid-revshare",
                "title": "RevShare",
                "name": "revshare",
                "calc_mode": "formula",
                "formula": "[Revenue] / 100",
                "data_type": "float",
                "cast": "float",
                "type": "MEASURE",
                "aggregation": "sum",
                "hidden": False,
                "description": "",
            },
            {
                "guid": "guid-cost",
                "title": "Cost",
                "name": "cost",
                "calc_mode": "direct",
                "data_type": "float",
                "cast": "float",
                "type": "MEASURE",
                "aggregation": "sum",
                "hidden": True,
                "description": "Internal cost metric",
            },
            {
                "guid": "guid-scale",
                "title": "Scale",
                "name": "scale",
                "calc_mode": "parameter",
                "cast": "integer",
                "default_value": 10,
                "hidden": False,
                "description": "Scaling parameter",
            },
            {
                "guid": "guid-region",
                "title": "Region",
                "name": "region",
                "calc_mode": "direct",
                "data_type": "string",
                "cast": "string",
                "type": "DIMENSION",
                "hidden": False,
                "description": "",
            },
        ),
    )


def test_find_field_by_guid() -> None:
    ds = _dataset_with_rich_schema()
    field = ds.find_field("guid-revenue")
    assert field is not None
    assert field.title == "Revenue"


def test_find_field_by_title() -> None:
    ds = _dataset_with_rich_schema()
    field = ds.find_field("Revenue")
    assert field is not None
    assert field.guid == "guid-revenue"


def test_find_field_by_name() -> None:
    ds = _dataset_with_rich_schema()
    field = ds.find_field("order_date")
    assert field is not None
    assert field.title == "Order Date"


def test_find_field_guid_wins_over_title() -> None:
    ds = Dataset(
        id="ds-test",
        installation="yacloud",
        sources=SourcesProxy([]),
        result_schema=(
            {"guid": "x", "title": "y", "name": "field_a", "calc_mode": "direct"},
            {"guid": "z", "title": "x", "name": "field_b", "calc_mode": "direct"},
        ),
    )
    field = ds.find_field("x")
    assert field is not None
    assert field.guid == "x"
    assert field.title == "y"


def test_find_field_not_found() -> None:
    ds = _dataset_with_rich_schema()
    field = ds.find_field("nonexistent")
    assert field is None


def test_find_source_avatar_by_avatar_id() -> None:
    avatar = _dataset_for_update().find_source_avatar("avatar-1")

    assert avatar is not None
    assert avatar["source_id"] == "src-1"


def test_find_source_avatar_by_source_id() -> None:
    avatar = _dataset_for_update().find_source_avatar("src-1")

    assert avatar is not None
    assert avatar["id"] == "avatar-1"


def test_find_source_avatar_by_title() -> None:
    avatar = _dataset_for_update().find_source_avatar("orders")

    assert avatar is not None
    assert avatar["id"] == "avatar-1"


def test_find_source_avatar_id_wins_over_source_id_and_title() -> None:
    ds = Dataset(
        id="ds-test",
        source_avatars=(
            {"id": "match", "source_id": "source-a", "title": "Avatar A"},
            {"id": "avatar-b", "source_id": "match", "title": "Avatar B"},
            {"id": "avatar-c", "source_id": "source-c", "title": "match"},
        ),
    )

    avatar = ds.find_source_avatar("match")

    assert avatar is not None
    assert avatar["id"] == "match"


def test_find_source_avatar_not_found() -> None:
    assert _dataset_for_update().find_source_avatar("nonexistent") is None


def test_find_fields_grep_match() -> None:
    ds = _dataset_with_rich_schema()
    fields = ds.find_fields(grep="rev")
    assert len(fields) == 2
    titles = {f.title for f in fields}
    assert titles == {"Revenue", "RevShare"}


def test_find_fields_grep_case_insensitive() -> None:
    ds = _dataset_with_rich_schema()
    fields = ds.find_fields(grep="REV")
    assert len(fields) == 2


def test_find_fields_grep_invalid_regex() -> None:
    ds = _dataset_with_rich_schema()
    fields = ds.find_fields(grep="[")
    assert len(fields) == 6


def test_find_fields_calc_mode_filter() -> None:
    ds = _dataset_with_rich_schema()
    fields = ds.find_fields(calc_mode="formula")
    assert len(fields) == 1
    assert fields[0].title == "RevShare"


def test_find_fields_kind_filter() -> None:
    ds = _dataset_with_rich_schema()
    fields = ds.find_fields(kind="MEASURE")
    assert len(fields) == 3
    titles = {f.title for f in fields}
    assert titles == {"Revenue", "RevShare", "Cost"}


def test_find_fields_hidden_filter_true() -> None:
    ds = _dataset_with_rich_schema()
    fields = ds.find_fields(hidden=True)
    assert len(fields) == 1
    assert fields[0].title == "Cost"


def test_find_fields_hidden_filter_false() -> None:
    ds = _dataset_with_rich_schema()
    fields = ds.find_fields(hidden=False)
    assert len(fields) == 5


def test_find_fields_only_with_description() -> None:
    ds = _dataset_with_rich_schema()
    fields = ds.find_fields(only_with_description=True)
    assert len(fields) == 4
    titles = {f.title for f in fields}
    assert titles == {"Order Date", "Revenue", "Cost", "Scale"}


def test_find_fields_combined_filters_and() -> None:
    ds = _dataset_with_rich_schema()
    fields = ds.find_fields(calc_mode="direct", hidden=False)
    assert len(fields) == 3
    titles = {f.title for f in fields}
    assert titles == {"Order Date", "Revenue", "Region"}


def test_find_fields_empty_result() -> None:
    ds = _dataset_with_rich_schema()
    fields = ds.find_fields(kind="MEASURE", calc_mode="parameter")
    assert fields == []
