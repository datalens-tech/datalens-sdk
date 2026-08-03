from pathlib import Path

_SKILL_NAMES = ("datalens-sdk",)


def agent_skill_paths() -> list[str]:
    """Return directories containing the agent skills bundled with the SDK."""
    package_root = Path(__file__).resolve().parent
    packaged_skills = package_root / "skills"
    source_skills = package_root.parents[1] / "skills"
    skills_root = packaged_skills if packaged_skills.is_dir() else source_skills
    return [str(skills_root / name) for name in _SKILL_NAMES]


__all__ = ["agent_skill_paths"]
