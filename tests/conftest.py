import pytest

from src.directory import ClinicDirectory, build_directory


@pytest.fixture(scope="session")
def directory() -> ClinicDirectory:
    return build_directory()
