from importlib.metadata import version
from pathlib import Path

import datalens_sdk


def test_version_matches_installed_distribution_metadata() -> None:
    assert datalens_sdk.__version__ == version("datalens-sdk")


def test_agent_skill_paths_point_to_bundled_skills() -> None:
    skill_paths = datalens_sdk.agent_skill_paths()

    assert isinstance(skill_paths, list)
    assert len(skill_paths) == 1
    assert isinstance(skill_paths[0], str)
    skill_path = Path(skill_paths[0])
    assert skill_path.is_absolute()
    assert skill_path.name == "datalens-sdk"
    assert skill_path.joinpath("SKILL.md").is_file()
