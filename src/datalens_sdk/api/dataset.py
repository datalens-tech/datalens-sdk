from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import cast
import warnings

from pydantic import ValidationError

from datalens_sdk.api.entries import EntriesService
from datalens_sdk.converter.dataset import DatasetConverter, DatasetDtoModule
from datalens_sdk.domain.dataset import Dataset, DatasetCreate, Source
from datalens_sdk.domain.dataset_types import RawSchemaColumnPayload
from datalens_sdk.domain.dataset_update import DatasetUpdate
from datalens_sdk.domain.navigation import EntryRelation, Pager, RelationOptions
from datalens_sdk.domain.ports import DatasetOperations, NavigationOperations
from datalens_sdk.domain.specs.dataset import DatasetUpdateSpec
from datalens_sdk.domain.specs.raw_resource import RawCreateSpec, RawReplaceSpec
from datalens_sdk.errors import (
    DataLensValidationError,
    translate_dto_validation_error,
)
from datalens_sdk.http import DEFAULT_RETRY_POLICY, TRANSIENT_RETRY_POLICY, HTTPClientProtocol, RetryPolicy

LOGGER = logging.getLogger("datalens_sdk.http")


def _dataset_payload_with_component_errors(payload: object | None) -> dict[str, object] | None:
    if not isinstance(payload, Mapping):
        return None

    candidates: list[Mapping[object, object]] = [payload]
    details = payload.get("details")
    if isinstance(details, Mapping):
        data = details.get("data")
        if isinstance(data, Mapping):
            candidates.append(data)

    for candidate in candidates:
        dataset = candidate.get("dataset")
        if isinstance(dataset, Mapping) and "component_errors" in dataset:
            return {key: value for key, value in candidate.items() if isinstance(key, str)}
    return None


def _is_dataset_error_response(status_code: int, payload: object | None) -> bool:
    return status_code == 400 and _dataset_payload_with_component_errors(payload) is not None


class DatasetAPI:
    def __init__(self, client: HTTPClientProtocol) -> None:
        self._client = client

    @staticmethod
    def _log_component_errors(path: str, payload: Mapping[str, object]) -> None:
        dataset = payload.get("dataset")
        if not isinstance(dataset, Mapping):
            return
        component_errors = dataset.get("component_errors")
        if isinstance(component_errors, Mapping):
            if not component_errors.get("items"):
                return
        elif not component_errors:
            return
        LOGGER.warning(
            "DataLens dataset component errors: operation=%s component_errors=%r",
            path.removeprefix("/rpc/"),
            component_errors,
        )

    def _post(
        self,
        path: str,
        body: dict[str, object],
        *,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    ) -> dict[str, object]:
        payload = self._client.post_json_object(
            path,
            body,
            retry_policy=retry_policy,
            accept_response=_is_dataset_error_response,
        )
        accepted_payload = _dataset_payload_with_component_errors(payload)
        if accepted_payload is not None:
            payload = accepted_payload
        return payload

    def create(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post("/rpc/createDataset", payload)

    def get(
        self,
        dataset_id: str,
        workbook_id: str | None = None,
        rev_id: str | None = None,
    ) -> dict[str, object]:
        body: dict[str, object] = {"datasetId": dataset_id}
        if workbook_id is not None:
            body["workbookId"] = workbook_id
        if rev_id is not None:
            body["rev_id"] = rev_id
        return self._post("/rpc/getDataset", body, retry_policy=TRANSIENT_RETRY_POLICY)

    def update(self, payload: dict[str, object]) -> dict[str, object]:
        return self._post("/rpc/updateDataset", payload)

    def delete(self, dataset_id: str) -> None:
        self._post("/rpc/deleteDataset", {"datasetId": dataset_id})

    def validate(self, payload: dict[str, object]) -> dict[str, object]:
        path = "/rpc/validateDataset"
        response = self._post(path, payload, retry_policy=TRANSIENT_RETRY_POLICY)
        self._log_component_errors(path, response)
        return response


class DatasetService(DatasetOperations):
    def __init__(
        self,
        *,
        installation: str,
        api: DatasetAPI,
        entries_service: EntriesService,
        navigation_operations: NavigationOperations,
        dto_module: DatasetDtoModule | None = None,
    ) -> None:
        self._installation = installation
        self._api = api
        self._entries_service = entries_service
        self._navigation_operations = navigation_operations
        self._dto_module = dto_module

    def create_dataset(self, builder: DatasetCreate) -> Dataset:
        spec = builder.to_spec()
        state: dict[str, object] | None = None
        if spec.sources or spec.actions:
            validate_payload = DatasetConverter.from_domain_create_validate_step(
                sources=spec.sources,
                relations=spec.relations,
                existing_state=None,
                refresh_sources=True,
                actions=spec.actions,
            )
            validated = self._api.validate(validate_payload)
            state = DatasetConverter.state_from_read_response(validated)
            state["description"] = spec.description
            state = DatasetConverter.apply_rls2_changes(state, spec.rls2_changes)

        try:
            dto_obj = DatasetConverter.from_domain_create(spec, dto_module=self._dto_module)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation="createDataset", reason=str(exc)) from exc

        create_payload = dto_obj.to_payload()
        dataset_content = cast(dict[str, object], create_payload["dataset"])
        if state is not None:
            dataset_content.update(state)
        elif spec.rls2_changes:
            dataset_content.update(DatasetConverter.apply_rls2_changes(dataset_content, spec.rls2_changes))

        response = self._api.create(create_payload)
        dataset = DatasetConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=spec.location,
            name=spec.name,
            dto_module=self._dto_module,
        )
        return dataset

    def create_dataset_from_raw(self, spec: RawCreateSpec) -> Dataset:
        payload = DatasetConverter.from_raw_create(spec).to_payload()
        response = self._api.create(payload)
        return DatasetConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=spec.location,
            name=spec.name,
            dto_module=self._dto_module,
        )

    def get_dataset(
        self,
        dataset_id: str,
        workbook_id: str | None = None,
        rev_id: str | None = None,
    ) -> Dataset:
        response = self._api.get(dataset_id, workbook_id=workbook_id, rev_id=rev_id)
        return DatasetConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            id_fallback=dataset_id,
            dto_module=self._dto_module,
        )

    def update_dataset(self, builder: DatasetUpdate) -> Dataset:
        spec: DatasetUpdateSpec = builder.to_spec()
        dataset_id = spec.dataset_id
        if not dataset_id:
            raise ValueError("Cannot update dataset without an id")
        if spec.actions:
            validate_payload = DatasetConverter.from_domain_validate(spec)
            validated = self._api.validate(validate_payload)
            state = DatasetConverter.state_from_read_response(validated)
            if spec.name_change is not None:
                state["name"] = spec.name_change
        else:
            state = DatasetConverter.state_for_name_only(spec)
        state = DatasetConverter.apply_rls2_changes(state, spec.rls2_changes)
        response = self._api.update({"datasetId": dataset_id, "data": {"dataset": state}})
        return DatasetConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=spec.location,
            name=spec.name_change or spec.name,
            id_fallback=dataset_id,
            dto_module=self._dto_module,
        )

    def replace_dataset_from_raw(self, spec: RawReplaceSpec) -> Dataset:
        payload = DatasetConverter.from_raw_replace(spec).to_payload()
        response = self._api.update(payload)
        return DatasetConverter.to_domain(
            response,
            installation=self._installation,
            operations=self,
            location=spec.target_location,
            name=spec.target_name,
            id_fallback=spec.target_id,
            dto_module=self._dto_module,
        )

    def delete_dataset(self, dataset_id: str) -> None:
        self._api.delete(dataset_id)

    def rename_dataset(self, dataset: Dataset, name: str) -> Dataset:
        if not dataset.id:
            raise ValueError("Cannot rename a dataset without an id")
        self._entries_service.rename_entry(entry_id=dataset.id, name=name)
        return self.get_dataset(dataset.id, workbook_id=dataset.workbook_id)

    def get_entry_relations(self, entry_id: str, options: RelationOptions) -> Pager[EntryRelation]:
        return self._navigation_operations.get_entry_relations(entry_id, options)

    def validate_source(
        self,
        source: Source,
        *,
        strict: bool = False,
    ) -> tuple[tuple[RawSchemaColumnPayload, ...], bool]:
        payload = DatasetConverter.build_validate_source_payload(source)
        response = self._api.validate(payload)
        schema, valid = DatasetConverter.parse_validate_source_response(response, source.id)
        if not valid or not schema:
            message = f"Source {source.id!r} (type={source.source_type!r}) returned empty or invalid schema"
            if strict:
                raise DataLensValidationError(message)
            warnings.warn(message, stacklevel=2)
            return (), False
        return schema, valid
