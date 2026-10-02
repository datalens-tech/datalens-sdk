from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol, TypedDict, cast

from pydantic import TypeAdapter, ValidationError

from datalens_sdk._generated import dto as generated_dto
from datalens_sdk.converter.lakehouse_operation import LakehouseTimestampReadDTOProtocol, lakehouse_timestamp_from_dto
from datalens_sdk.domain.navigation import Page
from datalens_sdk.domain.ports import SparkJobOperations
from datalens_sdk.domain.spark_job import (
    SparkJob,
    SparkJobCatalogRef,
    SparkJobConnectSpec,
    SparkJobListOptions,
    SparkJobPySparkSpec,
    SparkJobSparkSpec,
    SparkJobStatus,
)
from datalens_sdk.errors import translate_dto_validation_error, translate_invalid_response_error


class SparkJobWriteDTOProtocol(Protocol):
    def to_payload(self) -> dict[str, object]: ...


class SparkJobWriteDTOClass(Protocol):
    def model_validate(self, obj: object) -> SparkJobWriteDTOProtocol: ...


class SparkJobReadDTOProtocol(Protocol):
    @property
    def created_at(self) -> LakehouseTimestampReadDTOProtocol: ...

    @property
    def started_at(self) -> LakehouseTimestampReadDTOProtocol | None: ...

    @property
    def finished_at(self) -> LakehouseTimestampReadDTOProtocol | None: ...

    def model_dump(self, *, mode: Literal["json"], by_alias: bool) -> dict[str, object]: ...


class SparkJobListReadDTOProtocol(Protocol):
    @property
    def jobs(self) -> list[SparkJobReadDTOProtocol]: ...

    def model_dump(self, *, mode: Literal["json"], by_alias: bool) -> dict[str, object]: ...


class SparkJobListReadDTOClass(Protocol):
    def model_validate(self, obj: object) -> SparkJobListReadDTOProtocol: ...


class SparkJobDtoModule(Protocol):
    GetSparkJobArgsDTO: SparkJobWriteDTOClass
    ListSparkJobsArgsDTO: SparkJobWriteDTOClass
    ListSparkJobsResultReadDTO: SparkJobListReadDTOClass
    SparkJobReadDTO: object


def _dto_module(dto_module: SparkJobDtoModule | None) -> SparkJobDtoModule:
    return cast(SparkJobDtoModule, generated_dto if dto_module is None else dto_module)


def _raw_mapping(value: object, *, operation: str, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise translate_invalid_response_error(operation=operation, reason=f"{field} is not an object")
    return cast(Mapping[str, object], value)


def _raw_timestamp(raw: Mapping[str, object], name: str) -> Mapping[str, object] | None:
    value = raw[name]
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} is not an object")
    return cast(Mapping[str, object], value)


class _CommonSpec(TypedDict):
    archive_uris: tuple[str, ...]
    file_uris: tuple[str, ...]
    jar_file_uris: tuple[str, ...]
    packages: tuple[str, ...]
    repositories: tuple[str, ...]
    exclude_packages: tuple[str, ...]
    properties: Mapping[str, str]


def _common_spec(data: Mapping[str, object]) -> _CommonSpec:
    return {
        "archive_uris": tuple(cast(list[str], data["archiveUris"])),
        "file_uris": tuple(cast(list[str], data["fileUris"])),
        "jar_file_uris": tuple(cast(list[str], data["jarFileUris"])),
        "packages": tuple(cast(list[str], data["packages"])),
        "repositories": tuple(cast(list[str], data["repositories"])),
        "exclude_packages": tuple(cast(list[str], data["excludePackages"])),
        "properties": cast(Mapping[str, str], data["properties"]),
    }


class SparkJobConverter:
    @staticmethod
    def get_payload(
        cluster_id: str, job_id: str, *, dto_module: SparkJobDtoModule | None = None
    ) -> SparkJobWriteDTOProtocol:
        return _dto_module(dto_module).GetSparkJobArgsDTO.model_validate({"clusterId": cluster_id, "jobId": job_id})

    @staticmethod
    def list_payload(
        options: SparkJobListOptions,
        *,
        page_token: str | None,
        dto_module: SparkJobDtoModule | None = None,
    ) -> SparkJobWriteDTOProtocol:
        payload: dict[str, object] = {"clusterId": options.cluster_id, "pageSize": options.page_size}
        if options.filters:
            payload["filter"] = list(options.filters)
        if page_token is not None:
            payload["pageToken"] = page_token
        return _dto_module(dto_module).ListSparkJobsArgsDTO.model_validate(payload)

    @staticmethod
    def to_job(
        raw: Mapping[str, object],
        *,
        installation: str,
        operations: SparkJobOperations | None,
        operation: Literal["getSparkJob", "listSparkJobs"],
        dto_module: SparkJobDtoModule | None = None,
    ) -> SparkJob:
        try:
            validated = cast(
                SparkJobReadDTOProtocol,
                TypeAdapter[object](_dto_module(dto_module).SparkJobReadDTO).validate_python(raw),
            )
        except ValidationError as exc:
            raise translate_dto_validation_error(operation=operation, reason=str(exc)) from exc
        return SparkJobConverter._to_job_from_validated(
            raw, validated=validated, installation=installation, operations=operations, operation=operation
        )

    @staticmethod
    def _to_job_from_validated(
        raw: Mapping[str, object],
        *,
        validated: SparkJobReadDTOProtocol,
        installation: str,
        operations: SparkJobOperations | None,
        operation: Literal["getSparkJob", "listSparkJobs"],
    ) -> SparkJob:
        try:
            data = validated.model_dump(mode="json", by_alias=True)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation=operation, reason=str(exc)) from exc
        try:
            kind = data.get("jobSpec")
            spec: SparkJobSparkSpec | SparkJobPySparkSpec | SparkJobConnectSpec | None
            if kind == "sparkJob":
                spark = cast(Mapping[str, object], data["sparkJob"])
                spec = SparkJobSparkSpec(
                    main_jar_file_uri=cast(str, spark["mainJarFileUri"]),
                    main_class=cast(str, spark["mainClass"]),
                    args=tuple(cast(list[str], spark["args"])),
                    **_common_spec(spark),
                )
            elif kind == "pysparkJob":
                pyspark = cast(Mapping[str, object], data["pysparkJob"])
                spec = SparkJobPySparkSpec(
                    main_python_file_uri=cast(str, pyspark["mainPythonFileUri"]),
                    python_file_uris=tuple(cast(list[str], pyspark["pythonFileUris"])),
                    args=tuple(cast(list[str], pyspark["args"])),
                    **_common_spec(pyspark),
                )
            elif kind == "sparkConnectJob":
                spec = SparkJobConnectSpec(**_common_spec(cast(Mapping[str, object], data["sparkConnectJob"])))
            else:
                spec = None
            created_at = lakehouse_timestamp_from_dto(_raw_timestamp(raw, "createdAt"), dto=validated.created_at)
            if created_at is None:
                raise ValueError("createdAt is required")
            return SparkJob(
                id=cast(str, data["id"]),
                cluster_id=cast(str, data["clusterId"]),
                installation=installation,
                name=cast(str, data["name"]),
                created_by=cast(str, data["createdBy"]),
                status=cast(SparkJobStatus, data["status"]),
                connect_url=cast(str, data["connectUrl"]),
                catalogs=tuple(
                    SparkJobCatalogRef(cast(str, cast(Mapping[str, object], item)["catalogId"]))
                    for item in cast(list[object], data["catalogs"])
                ),
                created_at=created_at,
                started_at=lakehouse_timestamp_from_dto(_raw_timestamp(raw, "startedAt"), dto=validated.started_at),
                finished_at=lakehouse_timestamp_from_dto(_raw_timestamp(raw, "finishedAt"), dto=validated.finished_at),
                spec=spec,
                raw=dict(raw),
                _operations=operations,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise translate_invalid_response_error(operation=operation, reason=str(exc)) from exc

    @staticmethod
    def to_page(
        raw: Mapping[str, object],
        *,
        installation: str,
        operations: SparkJobOperations | None,
        dto_module: SparkJobDtoModule | None = None,
    ) -> Page[SparkJob]:
        operation: Literal["listSparkJobs"] = "listSparkJobs"
        try:
            validated = _dto_module(dto_module).ListSparkJobsResultReadDTO.model_validate(raw)
        except ValidationError as exc:
            raise translate_dto_validation_error(operation=operation, reason=str(exc)) from exc
        data = validated.model_dump(mode="json", by_alias=True)
        jobs = raw.get("jobs")
        if not isinstance(jobs, list):
            raise translate_invalid_response_error(operation=operation, reason="jobs wire key is not an array")
        return Page(
            items=tuple(
                SparkJobConverter._to_job_from_validated(
                    _raw_mapping(raw_item, operation=operation, field="jobs item"),
                    validated=validated_item,
                    installation=installation,
                    operations=operations,
                    operation=operation,
                )
                for raw_item, validated_item in zip(jobs, validated.jobs, strict=True)
            ),
            next_page_token=cast(str, data["nextPageToken"]),
        )
