from __future__ import annotations

from pydantic import ValidationError
import pytest

from datalens_sdk._generated.dto import (
    DashboardCreateDTO,
    DashboardDeleteArgsDTO,
    DashboardGetArgsDTO,
    DashboardReadDTO,
    DashboardUpdateDTO,
)


def test_dashboard_create_payload_wraps_entry_and_skips_none_optionals() -> None:
    dto = DashboardCreateDTO(
        data={"schemeVersion": 8, "tabs": []},
        meta={},
        name="sales",
        workbook_id="wb-1",
    )

    payload = dto.to_payload()

    assert payload == {
        "entry": {
            "data": {"schemeVersion": 8, "tabs": []},
            "meta": {},
            "name": "sales",
            "workbookId": "wb-1",
        }
    }


def test_dashboard_create_payload_with_key_location() -> None:
    dto = DashboardCreateDTO(
        data={"tabs": []},
        meta={},
        key="Folder/sales",
        annotation={"description": "quarterly"},
    )

    payload = dto.to_payload()

    entry = payload["entry"]
    assert isinstance(entry, dict)
    assert entry["key"] == "Folder/sales"
    assert entry["annotation"] == {"description": "quarterly"}
    assert "name" not in entry
    assert "workbookId" not in entry


def test_dashboard_create_dto_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        DashboardCreateDTO(data={}, meta={}, unexpected="boom")  # type: ignore[call-arg]


def test_dashboard_write_dtos_meta_is_required_but_nullable() -> None:
    # DashboardMeta is type ["object", "null"] and required in create/update:
    # "meta": null must serialize, omitting meta must fail before HTTP.
    create_payload = DashboardCreateDTO(data={"tabs": []}, meta=None).to_payload()
    create_entry = create_payload["entry"]
    assert isinstance(create_entry, dict)
    assert create_entry["meta"] is None

    update_payload = DashboardUpdateDTO(entry_id="dash-1", data={"tabs": []}, meta=None, mode="save").to_payload()
    update_entry = update_payload["entry"]
    assert isinstance(update_entry, dict)
    assert update_entry["meta"] is None

    with pytest.raises(ValidationError):
        DashboardCreateDTO(data={})  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        DashboardUpdateDTO(entry_id="dash-1", data={}, mode="save")  # type: ignore[call-arg]


def test_dashboard_update_payload_shape() -> None:
    dto = DashboardUpdateDTO(
        entry_id="dash-1",
        data={"tabs": []},
        meta={},
        mode="publish",
        rev_id="rev-9",
        lock_token="lock-7",
        annotation={"description": "updated"},
    )

    assert dto.to_payload() == {
        "entry": {
            "entryId": "dash-1",
            "data": {"tabs": []},
            "meta": {},
            "annotation": {"description": "updated"},
            "revId": "rev-9",
        },
        "mode": "publish",
        "lockToken": "lock-7",
    }


def test_dashboard_update_payload_skips_none_optionals() -> None:
    dto = DashboardUpdateDTO(entry_id="dash-1", data={}, meta={}, mode="save")

    payload = dto.to_payload()

    entry = payload["entry"]
    assert isinstance(entry, dict)
    assert "revId" not in entry
    assert "annotation" not in entry
    assert "lockToken" not in payload


def test_dashboard_read_dto_captures_raw_and_ignores_unknown_fields() -> None:
    wire = {
        "entryId": "dash-1",
        "key": "Folder/sales",
        "data": {"tabs": []},
        "revId": "rev-1",
        "savedId": "rev-1",
        "publishedId": "rev-0",
        "workbookId": "wb-1",
        "futureField": {"nested": True},
    }

    dto = DashboardReadDTO.model_validate(wire)

    assert dto.entry_id == "dash-1"
    assert dto.rev_id == "rev-1"
    assert dto.saved_id == "rev-1"
    assert dto.published_id == "rev-0"
    assert dto.workbook_id == "wb-1"
    assert dto.raw == wire


def test_dashboard_get_args_payload_includes_only_set_fields() -> None:
    minimal = DashboardGetArgsDTO(dashboard_id="dash-1")
    assert minimal.to_payload() == {"dashboardId": "dash-1"}

    full = DashboardGetArgsDTO(
        dashboard_id="dash-1",
        workbook_id="wb-1",
        rev_id="rev-3",
        branch="published",
        include_favorite=True,
        include_links=False,
        include_permissions=True,
    )
    assert full.to_payload() == {
        "dashboardId": "dash-1",
        "workbookId": "wb-1",
        "revId": "rev-3",
        "branch": "published",
        "includeFavorite": True,
        "includeLinks": False,
        "includePermissions": True,
    }


def test_dashboard_delete_args_payload() -> None:
    assert DashboardDeleteArgsDTO(dashboard_id="dash-1").to_payload() == {"dashboardId": "dash-1"}
    assert DashboardDeleteArgsDTO(dashboard_id="dash-1", lock_token="lock-7").to_payload() == {
        "dashboardId": "dash-1",
        "lockToken": "lock-7",
    }
