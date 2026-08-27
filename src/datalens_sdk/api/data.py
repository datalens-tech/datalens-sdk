from datalens_sdk.http import TRANSIENT_RETRY_POLICY, HTTPClientProtocol


class DataAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    def get_dataset_data(self, payload: dict[str, object]) -> dict[str, object]:
        return self._client.post_json_object(
            "/rpc/getDatasetData",
            payload,
            retry_policy=TRANSIENT_RETRY_POLICY,
        )
