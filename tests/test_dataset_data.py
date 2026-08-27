import json
from typing import cast

import httpx
import pytest

import datalens_sdk as dl


class RecordedTransport:
    def __init__(self, responses: list[httpx.Response] | httpx.Response) -> None:
        self.requests: list[httpx.Request] = []
        self._responses = list(responses) if isinstance(responses, list) else [responses]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self._responses.pop(0)
        response.request = request
        return response

    def request_json(self, index: int = 0) -> dict[str, object]:
        payload: object = json.loads(self.requests[index].content.decode())
        assert isinstance(payload, dict)
        return cast(dict[str, object], payload)


def _response() -> dict[str, object]:
    return {
        "schema": [
            {"name": "Region", "guid": "region", "type": "string", "future": "ignored"},
            {"name": "Sales", "guid": "sales", "type": "float"},
        ],
        "rows": [["East", 12.5], ["West", None]],
        "future": "ignored",
    }


@pytest.mark.parametrize("client_cls", [dl.DataLensClientYC, dl.DataLensClientEnterprise])
def test_get_dataset_data_serializes_typed_query_and_parses_rows(
    client_cls: type[dl.DataLensClientYC] | type[dl.DataLensClientEnterprise],
) -> None:
    recorder = RecordedTransport(httpx.Response(200, json=_response()))
    client = client_cls(
        auth=None,
        base_url="http://test",
        transport=httpx.MockTransport(recorder.handler),
    )
    region = dl.DatasetField(
        guid="region",
        title="Region",
        name="region",
        calc_mode="direct",
        dataset_id="dataset-1",
    )
    sales = dl.DatasetField(
        guid="sales",
        title="Sales",
        name="sales",
        calc_mode="direct",
        dataset_id="dataset-1",
    )
    threshold = dl.DatasetField(
        guid="threshold",
        title="Threshold",
        name="threshold",
        calc_mode="parameter",
        dataset_id="dataset-1",
    )

    result = client.data.get_dataset_data(
        dataset_id="dataset-1",
        columns=[region, sales],
        filters=[dl.DatasetDataFilter(field=region, operation="IN", values=("East", "West"))],
        params=[dl.DatasetDataParameter(field=threshold, value=100)],
        sort=[dl.DatasetDataSort(field=sales, direction="desc")],
        limit=25,
        offset=50,
    )

    assert recorder.requests[0].url.path == "/rpc/getDatasetData"
    assert recorder.request_json() == {
        "datasetId": "dataset-1",
        "columns": ["region", "sales"],
        "filters": [{"guid": "region", "operation": "in", "values": ["East", "West"]}],
        "params": [{"guid": "threshold", "value": 100}],
        "sort": [{"guid": "sales", "direction": "desc"}],
        "limit": 25,
        "offset": 50,
    }
    assert result == dl.DatasetData(
        schema=(
            dl.DatasetDataColumn(name="Region", guid="region", type="string"),
            dl.DatasetDataColumn(name="Sales", guid="sales", type="float"),
        ),
        rows=(("East", 12.5), ("West", None)),
    )


def test_get_dataset_data_sends_safe_default_limit_and_omits_empty_options() -> None:
    recorder = RecordedTransport(httpx.Response(200, json={"schema": [], "rows": []}))
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))

    result = client.data.get_dataset_data(dataset_id="dataset-1", columns=["sales"])

    assert result == dl.DatasetData(schema=(), rows=())
    assert recorder.request_json() == {
        "datasetId": "dataset-1",
        "columns": ["sales"],
        "limit": 500,
    }


def test_get_dataset_data_preserves_mixed_response_values() -> None:
    markup = {"type": "url", "url": "asdf", "content": {"type": "text", "content": "qwer"}}
    response = {
        "schema": [
            {"name": "markup field", "guid": "markup", "type": "markup"},
            {"name": "tree field", "guid": "tree", "type": "tree_str"},
            {"name": "sys2", "guid": "sys2", "type": "string"},
            {"name": "invalid field example", "guid": "invalid", "type": "string"},
            {"name": "bool field", "guid": "bool", "type": "boolean"},
            {"name": "ClientID", "guid": "client_id", "type": "string"},
            {"name": "Discount", "guid": "discount", "type": "float"},
            {"name": "OrderDatetime", "guid": "ordered_at", "type": "genericdatetime"},
        ],
        "rows": [
            [
                markup,
                '["foo", "bar", "baz"]',
                "this text must not be visible ever",
                "foozxcv",
                "True",
                "6bISw",
                659.6,
                "2019-04-29T14:18:00",
            ]
        ],
    }
    recorder = RecordedTransport(httpx.Response(200, json=response))
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))

    result = client.data.get_dataset_data(dataset_id="dataset-1", columns=["markup"])

    assert tuple(column.type for column in result.schema) == (
        "markup",
        "tree_str",
        "string",
        "string",
        "boolean",
        "string",
        "float",
        "genericdatetime",
    )
    assert result.rows == (
        (
            markup,
            '["foo", "bar", "baz"]',
            "this text must not be visible ever",
            "foozxcv",
            "True",
            "6bISw",
            659.6,
            "2019-04-29T14:18:00",
        ),
    )


def test_get_dataset_data_preserves_unknown_response_column_type() -> None:
    recorder = RecordedTransport(
        httpx.Response(200, json={"schema": [{"name": "Future", "guid": "future", "type": "future"}], "rows": []})
    )
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))

    result = client.data.get_dataset_data(dataset_id="dataset-1", columns=["future"])

    assert result == dl.DatasetData(
        schema=(dl.DatasetDataColumn(name="Future", guid="future", type="future"),),
        rows=(),
    )


def test_get_dataset_data_validates_query_before_request() -> None:
    recorder = RecordedTransport(httpx.Response(200, json={"schema": [], "rows": []}))
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))
    foreign = dl.DatasetField(
        guid="sales",
        title="Sales",
        name="sales",
        calc_mode="direct",
        dataset_id="dataset-2",
    )

    with pytest.raises(dl.DataLensValidationError, match="columns must contain"):
        client.data.get_dataset_data(dataset_id="dataset-1", columns=[])
    with pytest.raises(dl.DataLensValidationError, match="between 1 and 100000"):
        client.data.get_dataset_data(dataset_id="dataset-1", columns=["sales"], limit=100001)
    with pytest.raises(dl.DataLensValidationError, match="requires sort"):
        client.data.get_dataset_data(dataset_id="dataset-1", columns=["sales"], offset=1)
    with pytest.raises(dl.DataLensValidationError, match="included in columns"):
        client.data.get_dataset_data(
            dataset_id="dataset-1",
            columns=["sales"],
            sort=[dl.DatasetDataSort(field="date", direction="asc")],
        )
    with pytest.raises(dl.DataLensValidationError, match="belongs to dataset"):
        client.data.get_dataset_data(dataset_id="dataset-1", columns=[foreign])

    assert recorder.requests == []


def test_get_dataset_data_rejects_bare_string_columns_before_request() -> None:
    recorder = RecordedTransport(httpx.Response(200, json={"schema": [], "rows": []}))
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))

    with pytest.raises(dl.DataLensValidationError, match="columns must be a sequence of field references"):
        client.data.get_dataset_data(dataset_id="dataset-1", columns="sales")

    assert recorder.requests == []


def test_get_dataset_data_rejects_malformed_response() -> None:
    recorder = RecordedTransport(httpx.Response(200, json={"schema": []}))
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))

    with pytest.raises(dl.DTOValidationError, match="getDatasetData"):
        client.data.get_dataset_data(dataset_id="dataset-1", columns=["sales"])


def test_get_dataset_data_retries_transient_failures() -> None:
    recorder = RecordedTransport(
        [
            httpx.Response(503, json={"message": "temporarily unavailable"}),
            httpx.Response(200, json={"schema": [], "rows": []}),
        ]
    )
    client = dl.DataLensClientYC(auth=None, transport=httpx.MockTransport(recorder.handler))

    assert client.data.get_dataset_data(dataset_id="dataset-1", columns=["sales"]).rows == ()
    assert [request.url.path for request in recorder.requests] == [
        "/rpc/getDatasetData",
        "/rpc/getDatasetData",
    ]
