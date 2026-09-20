from importlib.metadata import version

import pytest

import fastapi_infra


@pytest.mark.unit
def test_package_metadata_and_version() -> None:
    distribution_version = version("fastapi-infra")

    assert fastapi_infra.__version__ == distribution_version
    assert distribution_version == "0.1.0"
