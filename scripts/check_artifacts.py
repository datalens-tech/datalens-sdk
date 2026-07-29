from __future__ import annotations

import argparse
from email.parser import Parser
from pathlib import Path, PurePosixPath
import re
import tarfile
import zipfile

from packaging.requirements import InvalidRequirement, Requirement
import tomli


def _wheel_metadata(wheel: zipfile.ZipFile) -> tuple[str, str]:
    members = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
    if len(members) != 1:
        raise SystemExit(f"Expected one wheel METADATA file, found {members}")
    return members[0], wheel.read(members[0]).decode()


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement(requirement: str) -> Requirement:
    try:
        return Requirement(requirement)
    except InvalidRequirement as exc:
        raise SystemExit(f"Invalid Requires-Dist value: {requirement!r}") from exc


def _project_metadata(path: Path) -> tuple[str, str, set[Requirement]]:
    document = tomli.loads(path.read_text())
    project = document.get("project")
    if not isinstance(project, dict):
        raise SystemExit(f"{path} has no [project] table")
    name = project.get("name")
    version = project.get("version")
    dependencies = project.get("dependencies", [])
    if not isinstance(name, str) or not isinstance(version, str):
        raise SystemExit(f"{path} has invalid project name or version")
    if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
        raise SystemExit(f"{path} has invalid project dependencies")
    return name, version, {_requirement(item) for item in dependencies}


def _assert_safe_members(members: set[str], *, archive: str) -> None:
    forbidden_parts = {".git", ".mypy_cache", ".nox", ".pytest_cache", ".ruff_cache", "__pycache__"}
    offenders = [
        member
        for member in sorted(members)
        if PurePosixPath(member).is_absolute()
        or ".." in PurePosixPath(member).parts
        or forbidden_parts.intersection(PurePosixPath(member).parts)
    ]
    if offenders:
        raise SystemExit(f"{archive} contains unsafe or transient paths: {offenders}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--reference-wheel", type=Path)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--project-file", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--package", required=True)
    parser.add_argument("--required-wheel-member", action="append", default=[])
    parser.add_argument("--required-sdist-path", action="append", default=[])
    parser.add_argument("--forbidden-text", action="append", default=[])
    args = parser.parse_args()

    distribution, project_version, declared_requirements = _project_metadata(args.project_file)
    package_path = args.package.replace(".", "/")
    with zipfile.ZipFile(args.wheel) as wheel:
        wheel_members = set(wheel.namelist())
        _assert_safe_members(wheel_members, archive="wheel")
        metadata_member, metadata_text = _wheel_metadata(wheel)
        metadata = Parser().parsestr(metadata_text)
        if _canonical_name(metadata["Name"]) != _canonical_name(distribution):
            raise SystemExit(f"Unexpected distribution name: {metadata['Name']!r}")
        artifact_version = metadata["Version"]
        if artifact_version != project_version:
            raise SystemExit(
                f"Wheel version {artifact_version!r} does not match {args.project_file} version {project_version!r}"
            )

        required_wheel = {
            f"{package_path}/__init__.py",
            f"{package_path}/py.typed",
            *args.required_wheel_member,
        }
        missing = sorted(required_wheel - wheel_members)
        if missing:
            raise SystemExit(f"Wheel is missing required files: {missing}")

        dist_info_prefix = metadata_member.removesuffix("METADATA")
        allowed_prefixes = (f"{package_path}/", dist_info_prefix)
        unexpected = sorted(name for name in wheel_members if not name.startswith(allowed_prefixes))
        if unexpected:
            raise SystemExit(f"Wheel contains unexpected files: {unexpected}")

        requirements = metadata.get_all("Requires-Dist", [])
        artifact_requirements = {_requirement(requirement) for requirement in requirements}
        if artifact_requirements != declared_requirements:
            raise SystemExit(
                "Wheel dependencies do not match pyproject.toml: "
                f"wheel={sorted(map(str, artifact_requirements))!r}, "
                f"project={sorted(map(str, declared_requirements))!r}"
            )

        wheel_text = "\n".join(
            wheel.read(name).decode(errors="ignore")
            for name in wheel_members
            if name.endswith((".json", ".md", ".py", ".txt"))
        )
        wheel_payload = {name: wheel.read(name) for name in wheel_members if name.startswith(f"{package_path}/")}

    if args.reference_wheel is not None:
        with zipfile.ZipFile(args.reference_wheel) as reference_wheel:
            reference_payload = {
                name: reference_wheel.read(name)
                for name in reference_wheel.namelist()
                if name.startswith(f"{package_path}/")
            }
        if wheel_payload != reference_payload:
            changed = sorted(wheel_payload.keys() ^ reference_payload.keys())
            changed.extend(
                name
                for name in sorted(wheel_payload.keys() & reference_payload.keys())
                if wheel_payload[name] != reference_payload[name]
            )
            raise SystemExit(f"Wheel package payload differs from reference wheel: {changed}")

    with tarfile.open(args.sdist) as sdist:
        tar_members = sdist.getmembers()
        unsupported_members = sorted(member.name for member in tar_members if not (member.isfile() or member.isdir()))
        if unsupported_members:
            raise SystemExit(f"Sdist contains links or special members: {unsupported_members}")
        sdist_members = {member.name for member in tar_members}
        _assert_safe_members(sdist_members, archive="sdist")
        roots = {PurePosixPath(name).parts[0] for name in sdist_members if PurePosixPath(name).parts}
        if len(roots) != 1:
            raise SystemExit(f"Expected one sdist root, found {sorted(roots)}")
        root = next(iter(roots))
        expected_root = f"{distribution.replace('-', '_')}-{artifact_version}"
        if root != expected_root:
            raise SystemExit(f"Unexpected sdist root {root!r}; expected {expected_root!r} from wheel metadata")
        pkg_info_members = [member for member in tar_members if member.name == f"{root}/PKG-INFO"]
        if len(pkg_info_members) != 1:
            raise SystemExit(f"Expected one sdist PKG-INFO file, found {pkg_info_members}")
        pkg_info_file = sdist.extractfile(pkg_info_members[0])
        if pkg_info_file is None:
            raise SystemExit("Could not read sdist PKG-INFO")
        pkg_info = Parser().parsestr(pkg_info_file.read().decode())
        pkg_info_requirements = {_requirement(requirement) for requirement in pkg_info.get_all("Requires-Dist", [])}
        if (
            _canonical_name(pkg_info["Name"]) != _canonical_name(metadata["Name"])
            or pkg_info["Version"] != artifact_version
            or pkg_info_requirements != artifact_requirements
        ):
            raise SystemExit(
                "Wheel and sdist metadata disagree: "
                f"wheel={metadata['Name']!r} {artifact_version!r}, "
                f"sdist={pkg_info['Name']!r} {pkg_info['Version']!r}, "
                f"wheel requirements={sorted(map(str, artifact_requirements))!r}, "
                f"sdist requirements={sorted(map(str, pkg_info_requirements))!r}"
            )
        required_sdist = {f"{root}/{path}" for path in args.required_sdist_path}
        missing = sorted(required_sdist - sdist_members)
        if missing:
            raise SystemExit(f"Sdist is missing required files: {missing}")
        sdist_text = "\n".join(
            sdist.extractfile(member).read().decode(errors="ignore")
            for member in tar_members
            if member.isfile() and member.name.endswith((".json", ".md", ".py", ".txt", ".toml", ".yml", ".yaml"))
        )

    combined_text = f"{wheel_text}\n{sdist_text}"
    leaked = [text for text in args.forbidden_text if text in combined_text]
    if leaked:
        raise SystemExit(f"Artifacts contain forbidden text: {leaked}")


if __name__ == "__main__":
    main()
