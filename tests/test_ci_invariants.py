from __future__ import annotations

import ast
from collections.abc import Iterable
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys
from typing import cast, get_args

from datalens_sdk._generated import dto
from datalens_sdk.domain import dashboard_types, entry_types

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "datalens_sdk"
FORBIDDEN_GATEWAY_FRAGMENT = "/" + "gateway"
RLS2_FIELD = "rls2"
RAW_ONLY_MUTATION_METHODS = frozenset(
    {
        "create_from_file",
        "create_from_raw",
        "from_file",
        "from_raw",
        "from_snapshot",
        "replace_from_file",
        "replace_from_raw",
    }
)
RAW_MUTATION_IMPORT_PREFIXES = (
    "datalens_sdk.converter.raw",
    "datalens_sdk.domain.raw_",
    "datalens_sdk.domain.specs.raw_resource",
)
RAW_MUTATION_FACTORIES = {
    "connection": "RawConnection",
    "dataset": "RawDataset",
    "dashboard": "RawDashboard",
    "wizard_chart": "RawWizardChart",
    "editor_chart": "RawEditorChart",
    "ql_chart": "RawQLChart",
}
RAW_DOMAIN_INFRASTRUCTURE = frozenset(
    {
        "domain/__init__.py",
        "domain/ports.py",
        "domain/raw_dashboard.py",
        "domain/raw_resource.py",
        "domain/specs/raw_resource.py",
    }
)


def _python_files(*parts: str) -> Iterable[Path]:
    base = SRC.joinpath(*parts)
    if base.is_file():
        yield base
        return
    yield from base.rglob("*.py")


def _imports(path: Path, *, include_type_checking: bool = False) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: set[str] = set()

    def is_type_checking_test(node: ast.expr) -> bool:
        return (isinstance(node, ast.Name) and node.id == "TYPE_CHECKING") or (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "typing"
            and node.attr == "TYPE_CHECKING"
        )

    class ImportVisitor(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import) -> None:
            found.update(alias.name for alias in node.names)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if node.module:
                found.add(node.module)

        def visit_If(self, node: ast.If) -> None:
            if is_type_checking_test(node.test) and not include_type_checking:
                for child in node.orelse:
                    self.visit(child)
                return
            self.generic_visit(node)

    ImportVisitor().visit(tree)
    return found


def _is_raw_mutation_symbol(name: str) -> bool:
    return name.startswith("Raw") and name.endswith(("Create", "Factory", "Namespace", "Replace", "Spec", "Update"))


def _from_imports(tree: ast.AST) -> set[tuple[str, str]]:
    return {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }


def _raw_mutation_symbols(tree: ast.AST) -> set[str]:
    names = {name for _, name in _from_imports(tree)}
    names.update(node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute))
    return {name for name in names if _is_raw_mutation_symbol(name)}


def _calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                found.add(func.id)
            elif isinstance(func, ast.Attribute):
                found.add(func.attr)
    return found


def _generated_manifest() -> list[str]:
    scripts = ROOT / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        namespace = runpy.run_path(str(scripts / "check_generated.py"))
    finally:
        sys.path.pop(0)
    return cast(list[str], namespace["GENERATED_FILES"])


def test_codegen_output_matches_committed_files(tmp_path: Path) -> None:
    out = tmp_path / "generated"

    subprocess.run(
        [sys.executable, "scripts/generate_sdk.py", "--output-root", str(out)],
        cwd=ROOT,
        check=True,
    )

    generated = out / "src" / "datalens_sdk" / "_generated"
    expected = {path.relative_to(out).as_posix() for path in generated.rglob("*") if path.is_file()}
    assert set(_generated_manifest()) == expected

    for relative in _generated_manifest():
        assert (out / relative).read_text() == (ROOT / relative).read_text(), relative


def test_runtime_and_domain_do_not_import_generated_or_transport() -> None:
    runtime_allowed = {"datalens_sdk._runtime.recorder"}
    for path in _python_files("_runtime"):
        imports = _imports(path)
        if path.with_suffix("").as_posix().endswith(tuple(runtime_allowed)):
            continue
        assert not any("_generated" in module for module in imports), path

    for path in _python_files("domain"):
        imports = _imports(path)
        assert not any("_generated" in module for module in imports), path
        assert not any(module.startswith("datalens_sdk.clients") for module in imports), path
        assert "httpx" not in imports, path


def test_raw_serialization_layers_preserve_public_and_domain_boundaries() -> None:
    forbidden_raw_operation_imports = (
        "datalens_sdk._generated",
        "datalens_sdk.api",
        "datalens_sdk.converter",
    )
    for filename in ("raw_resource.py", "raw_dashboard.py"):
        path = SRC / "domain" / filename
        imports = _imports(path)
        assert not any(module.startswith(forbidden_raw_operation_imports) for module in imports), path
        assert "httpx" not in imports, path


def test_typed_and_raw_mutation_builder_branches_are_disjoint() -> None:
    typed_branch_files = list(_python_files("_generated", "builders"))
    typed_branch_files.extend(
        path for path in _python_files("domain") if path.relative_to(SRC).as_posix() not in RAW_DOMAIN_INFRASTRUCTURE
    )
    typed_branch_files.extend(_python_files("_runtime"))

    offenders: list[str] = []
    for path in typed_branch_files:
        rel = path.relative_to(SRC).as_posix()
        raw_imports = sorted(
            module
            for module in _imports(path, include_type_checking=True)
            if module == "datalens_sdk.raw" or module.startswith(RAW_MUTATION_IMPORT_PREFIXES)
        )
        if raw_imports:
            offenders.append(f"{rel}: imports {raw_imports}")

        tree = ast.parse(path.read_text(), filename=str(path))
        raw_symbols = sorted(_raw_mutation_symbols(tree))
        if raw_symbols:
            offenders.append(f"{rel}: uses raw mutation symbols {raw_symbols}")

    client_path = SRC / "client.py"
    client_tree = ast.parse(client_path.read_text(), filename=str(client_path))
    client_raw_imports = {
        (module, name)
        for module, name in _from_imports(client_tree)
        if module == "datalens_sdk.raw" or _is_raw_mutation_symbol(name)
    }
    expected_client_raw_imports = {("datalens_sdk.raw", "RawNamespace")}
    if client_raw_imports != expected_client_raw_imports:
        offenders.append(
            f"client.py: raw imports are {sorted(client_raw_imports)}, expected {sorted(expected_client_raw_imports)}"
        )

    client_raw_symbols = sorted(_raw_mutation_symbols(client_tree) - {"RawNamespace"})
    if client_raw_symbols:
        offenders.append(f"client.py: uses raw mutation symbols {client_raw_symbols}")

    for path in (*typed_branch_files, client_path):
        rel = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(), filename=str(path))
        raw_methods = sorted(
            {
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in RAW_ONLY_MUTATION_METHODS
            }
        )
        if raw_methods:
            offenders.append(f"{rel}: declares {raw_methods}")

    assert offenders == []


def test_raw_mutation_namespace_uses_operation_resource_factory_order() -> None:
    raw_path = SRC / "raw.py"
    tree = ast.parse(raw_path.read_text(), filename=str(raw_path))
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}

    def annotated_attributes(class_name: str) -> set[str]:
        return {
            node.target.id
            for node in classes[class_name].body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }

    assert annotated_attributes("RawNamespace") == {"create", "replace"}
    assert annotated_attributes("RawCreateNamespace") == set(RAW_MUTATION_FACTORIES)
    assert annotated_attributes("RawReplaceNamespace") == set(RAW_MUTATION_FACTORIES)

    for stem in RAW_MUTATION_FACTORIES.values():
        for operation in ("Create", "Replace"):
            factory_name = f"{stem}{operation}Factory"
            methods = {
                node.name
                for node in classes[factory_name].body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            assert methods == {"__call__", "__init__", "from_file"}, factory_name

            call = next(
                node
                for node in classes[factory_name].body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "__call__"
            )
            assert [argument.arg for argument in call.args.args] == ["self"], factory_name
            assert "response_snapshot" in {argument.arg for argument in call.args.kwonlyargs}, factory_name

    old_resource_namespaces = {f"{stem}Namespace" for stem in RAW_MUTATION_FACTORIES.values()}
    assert old_resource_namespaces.isdisjoint(classes)


def test_api_namespaces_send_only_through_shared_http_client() -> None:
    offenders: list[str] = []
    forbidden_calls = {"post", "request", "raise_for_status"}
    for path in _python_files("api"):
        imports = _imports(path)
        calls = _calls(path)
        if "httpx" in imports or calls & forbidden_calls:
            offenders.append(path.relative_to(SRC).as_posix())
    assert offenders == []


def test_generated_imports_are_limited_to_expected_layers() -> None:
    allowed_parts = {
        "converter",
        "_runtime/recorder.py",
        "_generated",
    }
    offenders: list[str] = []
    for path in _python_files():
        if any(part in path.as_posix() for part in allowed_parts):
            continue
        if any("_generated" in module for module in _imports(path)):
            offenders.append(str(path.relative_to(SRC)))
    assert offenders == []


def test_dto_constructors_are_limited_to_converter_and_recorder() -> None:
    offenders: list[str] = []
    dto_names = {name for name in dir(dto) if name.endswith("DTO")}
    for path in _python_files():
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith(("converter/", "_generated/")) or rel == "_runtime/recorder.py":
            continue
        used = _calls(path) & dto_names
        if used:
            offenders.append(f"{rel}: {sorted(used)}")
    assert offenders == []


def test_dto_extra_config_is_strict_on_write_ignore_on_read() -> None:
    assert dto.ConnectionCreateDTO.model_config.get("extra") == "forbid"
    assert dto.DatasetCreateDTO.model_config.get("extra") == "forbid"
    assert dto.EntryMoveDTO.model_config.get("extra") == "forbid"
    assert dto.EntryRenameDTO.model_config.get("extra") == "forbid"
    assert dto.CollectionCreateDTO.model_config.get("extra") == "forbid"
    assert dto.CollectionMoveDTO.model_config.get("extra") == "forbid"
    assert dto.CollectionUpdateDTO.model_config.get("extra") == "forbid"
    assert dto.WorkbookCreateDTO.model_config.get("extra") == "forbid"
    assert dto.WorkbookMoveDTO.model_config.get("extra") == "forbid"
    assert dto.WorkbookUpdateDTO.model_config.get("extra") == "forbid"
    assert dto.FolderCreateDTO.model_config.get("extra") == "forbid"
    assert dto.FolderUpdateDTO.model_config.get("extra") == "forbid"
    assert dto.DashboardCreateDTO.model_config.get("extra") == "forbid"
    assert dto.DashboardUpdateDTO.model_config.get("extra") == "forbid"
    assert dto.ConnectionReadDTO.model_config.get("extra") == "ignore"
    assert dto.DatasetReadDTO.model_config.get("extra") == "ignore"
    assert dto.CollectionReadDTO.model_config.get("extra") == "ignore"
    assert dto.WorkbookReadDTO.model_config.get("extra") == "ignore"
    assert dto.FolderReadDTO.model_config.get("extra") == "ignore"
    assert dto.DashboardReadDTO.model_config.get("extra") == "ignore"


def test_generated_builder_signatures_do_not_expose_untyped_object_arguments() -> None:
    offenders: list[str] = []
    for path in _python_files("_generated", "builders"):
        rel = path.relative_to(SRC).as_posix()
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("def ") and ("value: object" in stripped or ": object | None" in stripped):
                offenders.append(f"{rel}:{lineno}: {stripped}")
    assert offenders == []


def test_no_loguru_domain_file_size_and_builder_location_invariants() -> None:
    offenders: list[str] = []
    for path in _python_files():
        rel = path.relative_to(SRC).as_posix()
        text = path.read_text()
        if "loguru" in text:
            offenders.append(f"{rel}: imports/mentions loguru")
        if rel.startswith("domain/") and len(text.splitlines()) > 650:
            offenders.append(f"{rel}: exceeds 650 LOC")
        if (
            "ConnectionCreateFactory" in text
            and "class " in text
            and "builder" in rel
            and not rel.startswith("_generated/builders/")
        ):
            offenders.append(f"{rel}: builder outside _generated/builders")
    assert offenders == []


def test_sdk_source_does_not_use_gateway_routes() -> None:
    offenders: list[str] = []
    for path in _python_files():
        if FORBIDDEN_GATEWAY_FRAGMENT in path.read_text():
            offenders.append(path.relative_to(SRC).as_posix())

    assert offenders == []


def test_dataset_sdk_source_mentions_only_rls2() -> None:
    unsupported_field = RLS2_FIELD.removesuffix("2")
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(unsupported_field)}(?![A-Za-z0-9_])")
    offenders = [path.relative_to(SRC).as_posix() for path in _python_files() if pattern.search(path.read_text())]

    assert offenders == []


def test_api_version_header_is_pinned_on_shared_client() -> None:
    header = "x-dl-api-version"
    header_users = sorted(path.relative_to(SRC).as_posix() for path in _python_files() if header in path.read_text())
    constant_owners = sorted(
        path.relative_to(SRC).as_posix() for path in _python_files() if "API_VERSION =" in path.read_text()
    )

    assert header_users == ["auth.py", "http.py"]
    assert constant_owners == ["api_version.py"]


def test_shared_entry_routes_are_owned_by_entries_api() -> None:
    routes = (
        "/rpc/getEntries",
        "/rpc/getEntriesRelations",
        "/rpc/listDirectory",
        "/rpc/moveFolderEntry",
        "/rpc/renameEntry",
    )
    users = sorted(
        path.relative_to(SRC).as_posix()
        for path in _python_files("api")
        if any(route in path.read_text() for route in routes)
    )

    assert users == ["api/entries.py"]


def test_entries_api_consumers_are_limited_to_shared_entry_layers() -> None:
    """Keep shared entry transport and wire payloads out of resource-specific services."""
    users = sorted(path.relative_to(SRC).as_posix() for path in _python_files() if "EntriesAPI" in path.read_text())

    assert users == ["api/entries.py", "api/navigation.py", "client.py"]


DASHBOARD_ROUTES = (
    "/rpc/getDashboard",
    "/rpc/createDashboard",
    "/rpc/updateDashboard",
    "/rpc/deleteDashboard",
)
SPEC_NAMES = ("yacloud", "enterprise")


def _spec_schemas(spec_name: str) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    spec = cast(dict[str, object], json.loads((ROOT / "spec" / f"{spec_name}.json").read_text()))
    paths = cast(dict[str, object], spec["paths"])
    components = cast(dict[str, object], spec["components"])
    schemas = cast(dict[str, dict[str, object]], components["schemas"])
    return paths, schemas


def _resolved_schema(
    schemas: dict[str, dict[str, object]],
    schema: dict[str, object],
) -> dict[str, object]:
    reference = schema.get("$ref")
    if not isinstance(reference, str):
        return schema
    return schemas[reference.rsplit("/", 1)[-1]]


def _dashboard_item_variants(schemas: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    data_props = cast(dict[str, dict[str, object]], schemas["DashDataV2"]["properties"])
    tab_schema = _resolved_schema(schemas, cast(dict[str, object], data_props["tabs"]["items"]))
    tab_props = cast(dict[str, dict[str, object]], tab_schema["properties"])
    items_schema = _resolved_schema(schemas, cast(dict[str, object], tab_props["items"]["items"]))
    return cast(list[dict[str, object]], items_schema["oneOf"])


def test_dashboard_routes_use_v2_roots() -> None:
    request_roots = {
        "/rpc/getDashboard": "GetDashboardV2Args",
        "/rpc/createDashboard": "CreateDashboardV2Args",
        "/rpc/updateDashboard": "UpdateDashboardV2Args",
        "/rpc/deleteDashboard": "DeleteDashboardArgs",
    }
    expected_schemas = {
        "CreateDashboardV2Args",
        "UpdateDashboardV2Args",
        "GetDashboardV2Args",
        "GetDashboardV2Result",
        "DeleteDashboardArgs",
        "DashDataV2",
        "DashboardV2",
    }
    for spec_name in SPEC_NAMES:
        paths, schemas = _spec_schemas(spec_name)
        for route in DASHBOARD_ROUTES:
            assert route in paths, (spec_name, route)
        missing_schemas = expected_schemas.difference(schemas)
        assert not missing_schemas, (spec_name, sorted(missing_schemas))
        for route, expected_root in request_roots.items():
            route_item = cast(dict[str, object], paths[route])
            operation = cast(dict[str, object], route_item["post"])
            request_body = cast(dict[str, object], operation["requestBody"])
            content = cast(dict[str, object], request_body["content"])
            media = cast(dict[str, object], content["application/json"])
            request_schema = cast(dict[str, object], media["schema"])
            assert request_schema["$ref"] == f"#/components/schemas/{expected_root}", (spec_name, route)

        get_route = cast(dict[str, object], paths["/rpc/getDashboard"])
        get_operation = cast(dict[str, object], get_route["post"])
        responses = cast(dict[str, object], get_operation["responses"])
        response = cast(dict[str, object], responses["200"])
        response_content = cast(dict[str, object], response["content"])
        response_media = cast(dict[str, object], response_content["application/json"])
        response_schema = cast(dict[str, object], response_media["schema"])
        assert response_schema["$ref"] == "#/components/schemas/GetDashboardV2Result", spec_name

        create_props = cast(dict[str, dict[str, object]], schemas["CreateDashboardV2Args"]["properties"])
        create_entry_branches = cast(list[dict[str, object]], create_props["entry"]["allOf"])
        create_entry_objects = [branch for branch in create_entry_branches if "properties" in branch]
        assert len(create_entry_objects) == 1, (spec_name, create_entry_branches)
        create_entry_props = cast(dict[str, dict[str, object]], create_entry_objects[0]["properties"])
        assert create_entry_props["data"]["$ref"] == "#/components/schemas/DashDataV2", spec_name

        update_props = cast(dict[str, dict[str, object]], schemas["UpdateDashboardV2Args"]["properties"])
        update_entry_props = cast(dict[str, dict[str, object]], update_props["entry"]["properties"])
        assert update_entry_props["data"]["$ref"] == "#/components/schemas/DashDataV2", spec_name

        result_props = cast(dict[str, dict[str, object]], schemas["GetDashboardV2Result"]["properties"])
        assert result_props["entry"]["$ref"] == "#/components/schemas/DashboardV2", spec_name

        dashboard_props = cast(dict[str, dict[str, object]], schemas["DashboardV2"]["properties"])
        assert dashboard_props["version"].get("enum") == [2], spec_name
        data_props = cast(dict[str, dict[str, object]], schemas["DashDataV2"]["properties"])
        assert "schemeVersion" not in data_props, spec_name
        assert "description" not in data_props, spec_name
        dashboard_data = dashboard_props["data"]
        dashboard_data_contract = {key: value for key, value in dashboard_data.items() if key != "description"}
        assert dashboard_data_contract == schemas["DashDataV2"], spec_name


def test_dashboard_domain_literals_match_spec_enums() -> None:
    for spec_name in SPEC_NAMES:
        _, schemas = _spec_schemas(spec_name)

        assert set(get_args(entry_types.EntryBranch)) == set(cast(list[str], schemas["EntryBranch"]["enum"])), spec_name
        assert set(get_args(entry_types.EntryUpdateMode)) == set(cast(list[str], schemas["EntryUpdateMode"]["enum"])), (
            spec_name
        )

        assert "DashDataV2" in schemas, spec_name
        data_props = cast(dict[str, dict[str, object]], schemas["DashDataV2"]["properties"])
        settings_props = cast(dict[str, dict[str, object]], data_props["settings"]["properties"])
        assert set(get_args(dashboard_types.DashboardLoadPriority)) == set(
            cast(list[str], settings_props["loadPriority"]["enum"])
        ), spec_name

        item_types: set[str] = set()
        title_sizes: set[str] = set()
        for variant in _dashboard_item_variants(schemas):
            variant = _resolved_schema(schemas, variant)
            variant_props = cast(dict[str, dict[str, object]], variant["properties"])
            enum = cast(list[str], variant_props["type"]["enum"])
            assert len(enum) == 1, (spec_name, enum)
            item_types.add(enum[0])
            if enum[0] == "title":
                data_schema = variant_props["data"]
                data_props = cast(dict[str, dict[str, object]], data_schema["properties"])
                size_branches = cast(list[dict[str, object]], data_props["size"]["anyOf"])
                string_branches = [branch for branch in size_branches if branch.get("type") == "string"]
                assert len(string_branches) == 1, (spec_name, size_branches)
                title_sizes.update(cast(list[str], string_branches[0]["enum"]))
        assert set(get_args(dashboard_types.DashboardItemType)) == item_types, spec_name
        assert set(get_args(dashboard_types.DashboardTitleSize)) == title_sizes, spec_name


def test_api_and_converter_do_not_call_private_setters() -> None:
    forbidden_attrs = {"_set_placeholder", "_set_tab"}
    offenders: list[str] = []
    for part in ("api", "converter"):
        for path in _python_files(part):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in forbidden_attrs:
                    offenders.append(f"{path.relative_to(SRC).as_posix()}:{node.lineno}: {node.attr}")
    assert offenders == []


def test_api_and_converter_do_not_access_builder_private_attrs() -> None:
    offenders: list[str] = []
    for part in ("api", "converter"):
        for path in _python_files(part):
            rel = path.relative_to(SRC).as_posix()
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute):
                    continue
                if not node.attr.startswith("_"):
                    continue
                value = node.value
                if isinstance(value, ast.Name) and value.id.endswith("builder"):
                    offenders.append(f"{rel}:{node.lineno}: {value.id}.{node.attr}")
    assert offenders == []
