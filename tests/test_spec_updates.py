from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from scripts import update_specs
else:
    script = Path(__file__).resolve().parents[1] / "scripts" / "update_specs.py"
    module_spec = importlib.util.spec_from_file_location("sdk_update_specs", script)
    assert module_spec is not None
    assert module_spec.loader is not None
    update_specs = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = update_specs
    module_spec.loader.exec_module(update_specs)


def _spec(connectors: dict[str, str], sources: dict[str, str], *, version: str) -> dict[str, object]:
    return {
        "info": {"version": version},
        "paths": {"/rpc/getRevisions": {"post": {"x-mcp-scope": "read"}}},
        "components": {
            "schemas": {
                "ConnectionCreate": {"discriminator": {"mapping": connectors}},
                "DataSourceStrict": {"discriminator": {"mapping": sources}},
                "SharedResult": {"description": version},
            }
        },
    }


def _sources(tmp_path: Path) -> dict[str, update_specs.SpecSource]:
    return {
        name: update_specs.SpecSource(url=f"https://example.test/{name}", destination=tmp_path / f"{name}.json")
        for name in ("yacloud", "enterprise")
    }


def test_enterprise_refresh_uses_one_download_and_preserves_only_enabled_variants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = _sources(tmp_path)
    existing = _spec({"pg": "old-pg"}, {"PG_TABLE": "old-table"}, version="old")
    sources["enterprise"].destination.write_text(update_specs.format_spec(existing))
    latest = _spec(
        {"pg": "new-pg", "cloud-only": "cloud-connector"},
        {"PG_TABLE": "new-table", "CLOUD_TABLE": "cloud-table"},
        version="latest",
    )
    requested: list[str] = []

    def download(url: str) -> bytes:
        requested.append(url)
        assert url == sources["yacloud"].url
        return json.dumps(latest).encode()

    monkeypatch.setattr(update_specs, "download", download)
    results = update_specs.update_specs(["yacloud"], sources=sources, derive_enterprise=True)

    assert requested == [sources["yacloud"].url]
    assert [result.installation for result in results] == ["yacloud", "enterprise"]
    assert all(result.changed for result in results)
    assert json.loads(sources["yacloud"].destination.read_text()) == latest
    assert json.loads(sources["enterprise"].destination.read_text()) == _spec(
        {"pg": "new-pg"}, {"PG_TABLE": "new-table"}, version="latest"
    )


@pytest.mark.parametrize("missing_schema", ["ConnectionCreate", "DataSourceStrict"])
def test_missing_enterprise_variant_aborts_before_writing_either_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing_schema: str
) -> None:
    sources = _sources(tmp_path)
    existing = _spec({"pg": "old-pg"}, {"PG_TABLE": "old-table"}, version="old")
    original = update_specs.format_spec(existing)
    for source in sources.values():
        source.destination.write_text(original)
    latest = _spec(
        {"cloud-only": "cloud-connector"} if missing_schema == "ConnectionCreate" else {"pg": "new-pg"},
        {"CLOUD_TABLE": "cloud-table"} if missing_schema == "DataSourceStrict" else {"PG_TABLE": "new-table"},
        version="latest",
    )
    monkeypatch.setattr(update_specs, "download", lambda _url: json.dumps(latest).encode())

    with pytest.raises(update_specs.SpecUpdateError, match=f"{missing_schema}: Enterprise variants missing"):
        update_specs.update_specs(["yacloud"], sources=sources, derive_enterprise=True)

    assert all(source.destination.read_text() == original for source in sources.values())


def test_enterprise_derivation_does_not_mutate_the_downloaded_spec() -> None:
    latest = _spec({"pg": "new-pg", "cloud-only": "cloud"}, {"PG_TABLE": "new-table"}, version="latest")
    original = deepcopy(latest)
    existing = _spec({"pg": "old-pg"}, {"PG_TABLE": "old-table"}, version="old")

    derived = update_specs.derive_enterprise_spec(latest, existing)

    assert derived != latest
    assert latest == original
