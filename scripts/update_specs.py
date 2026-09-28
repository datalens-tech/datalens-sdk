from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class SpecSource:
    url: str
    destination: Path
    default: bool = True


@dataclass(frozen=True)
class UpdateResult:
    installation: str
    destination: Path
    changed: bool


SOURCES: dict[str, SpecSource] = {
    "yacloud": SpecSource(
        url="https://api.datalens.tech/json",
        destination=ROOT / "spec" / "yacloud.json",
    ),
    "enterprise": SpecSource(
        url="https://api.enterprise.dev.datalens.tech/json",
        destination=ROOT / "spec" / "enterprise.json",
        default=False,
    ),
}


class SpecUpdateError(RuntimeError):
    pass


def download(url: str) -> bytes:
    try:
        with urlopen(url, timeout=30) as response:
            return cast(bytes, response.read())
    except HTTPError as error:
        raise SpecUpdateError(f"{url}: HTTP {error.code}") from error
    except URLError as error:
        raise SpecUpdateError(f"{url}: {error.reason}") from error
    except OSError as error:
        raise SpecUpdateError(f"{url}: {error}") from error


def parse_spec(payload: bytes, *, installation: str) -> dict[str, object]:
    try:
        document = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise SpecUpdateError(f"{installation}: response is not valid JSON") from error
    if not isinstance(document, dict):
        raise SpecUpdateError(f"{installation}: response must be a JSON object")
    return cast(dict[str, object], document)


def format_spec(document: Mapping[str, object]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def discriminator_mapping(document: Mapping[str, object], schema: str) -> dict[str, str]:
    value: object = document
    for key in ("components", "schemas", schema, "discriminator", "mapping"):
        if not isinstance(value, dict) or key not in value:
            raise SpecUpdateError(f"{schema}: missing discriminator mapping")
        value = value[key]
    if (
        not isinstance(value, dict)
        or not value
        or not all(isinstance(key, str) and isinstance(ref, str) for key, ref in value.items())
    ):
        raise SpecUpdateError(f"{schema}: expected a non-empty mapping of names to schema references")
    return cast(dict[str, str], value)


def derive_enterprise_spec(
    yacloud: Mapping[str, object],
    existing_enterprise: Mapping[str, object],
) -> dict[str, object]:
    document = deepcopy(dict(yacloud))
    for schema in ("ConnectionCreate", "DataSourceStrict"):
        allowed = discriminator_mapping(existing_enterprise, schema)
        available = discriminator_mapping(document, schema)
        missing = allowed.keys() - available.keys()
        if missing:
            raise SpecUpdateError(f"{schema}: Enterprise variants missing from YaCloud: {', '.join(sorted(missing))}")
        selected = {name: available[name] for name in allowed}
        available.clear()
        available.update(selected)
    return document


def resolve_installations(
    requested: Sequence[str],
    *,
    sources: Mapping[str, SpecSource] = SOURCES,
) -> list[str]:
    if requested:
        return list(dict.fromkeys(requested))
    return [name for name, source in sources.items() if source.default]


def update_specs(
    installations: Sequence[str],
    *,
    sources: Mapping[str, SpecSource] = SOURCES,
    derive_enterprise: bool = False,
) -> list[UpdateResult]:
    installations = list(dict.fromkeys(installations))
    if derive_enterprise:
        installations = list(dict.fromkeys(["yacloud", *installations, "enterprise"]))
    documents: dict[str, dict[str, object]] = {}
    for installation in installations:
        if derive_enterprise and installation == "enterprise":
            continue
        documents[installation] = parse_spec(download(sources[installation].url), installation=installation)
    if derive_enterprise:
        path = sources["enterprise"].destination
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise SpecUpdateError(f"Cannot read Enterprise subset from {path}: {error}") from error
        documents["enterprise"] = derive_enterprise_spec(
            documents["yacloud"], parse_spec(payload, installation="enterprise")
        )
    formatted_specs: dict[str, str] = {}
    for installation in installations:
        formatted_specs[installation] = format_spec(documents[installation])

    results: list[UpdateResult] = []
    for installation in installations:
        source = sources[installation]
        formatted = formatted_specs[installation]
        current = source.destination.read_text(encoding="utf-8") if source.destination.exists() else None
        changed = current != formatted
        if changed:
            source.destination.write_text(formatted, encoding="utf-8")
        results.append(UpdateResult(installation=installation, destination=source.destination, changed=changed))
    return results


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    def installation(value: str) -> str:
        if value in SOURCES:
            return value
        choices = ", ".join(repr(name) for name in sorted(SOURCES))
        raise argparse.ArgumentTypeError(f"invalid choice: {value!r} (choose from {choices})")

    parser = argparse.ArgumentParser(description="Download and normalize DataLens OpenAPI specifications.")
    parser.add_argument(
        "--derive-enterprise",
        action="store_true",
        help="update both specs from YaCloud, preserving the existing Enterprise connector and source subsets",
    )
    parser.add_argument(
        "installations",
        nargs="*",
        type=installation,
        metavar="{" + ",".join(sorted(SOURCES)) + "}",
        help="installations to update (default: yacloud)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    installations = resolve_installations(cast(list[str], args.installations))
    try:
        results = update_specs(installations, derive_enterprise=args.derive_enterprise)
    except SpecUpdateError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    for result in results:
        status = "updated" if result.changed else "unchanged"
        print(f"{result.installation}: {status} {result.destination.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
