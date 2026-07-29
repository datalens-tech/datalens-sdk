from importlib.metadata import version

import datalens_sdk


def test_version_matches_installed_distribution_metadata() -> None:
    assert datalens_sdk.__version__ == version("datalens-sdk")
