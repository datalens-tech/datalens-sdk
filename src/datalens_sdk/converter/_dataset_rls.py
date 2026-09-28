from __future__ import annotations

from collections.abc import Mapping, Sequence

from datalens_sdk.domain.dataset_rls import RLSFieldRef, RLSRule
from datalens_sdk.domain.fields import DatasetField
from datalens_sdk.errors import DataLensValidationError


def resolve_rls_field(fields: Sequence[DatasetField], ref: RLSFieldRef) -> str:
    if not ref.value:
        raise DataLensValidationError("RLS field reference must not be empty")
    candidates = [field for field in fields if field.guid == ref.value]
    if not candidates and not ref.by_guid:
        candidates = [field for field in fields if ref.value in (field.name, field.title)]
        if not candidates:
            candidates = [field for field in fields if field.source == ref.value]
    guids = {field.guid for field in candidates if field.guid}
    if len(guids) > 1:
        raise DataLensValidationError(
            f"RLS field reference {ref.value!r} is ambiguous; pass a DatasetField or exact field GUID"
        )
    if not guids:
        raise DataLensValidationError(f"RLS field {ref.value!r} not found in the dataset schema")
    return guids.pop()


def rls_rule_payload(guid: str, rule: RLSRule) -> dict[str, object]:
    subject = {"subject_id": rule.subject_id, "subject_type": rule.subject_type}
    if rule.subject_name is not None:
        subject["subject_name"] = rule.subject_name
    entry: dict[str, object] = {"subject": subject, "field_guid": guid, "pattern_type": rule.pattern_type}
    if rule.allowed_value is not None:
        entry["allowed_value"] = rule.allowed_value
    return entry


def matches_rls_subject(entry: object, rule: RLSRule) -> bool:
    if not isinstance(entry, Mapping):
        return False
    subject = entry.get("subject")
    if not isinstance(subject, Mapping) or subject.get("subject_id") != rule.subject_id:
        return False
    if subject.get("subject_type") not in {"user", "group", "all", "userid"}:
        raise DataLensValidationError(
            f"Cannot replace RLS subject {rule.subject_id!r}: saved subject type is missing or unresolved"
        )
    return bool(subject["subject_type"] == rule.subject_type)
