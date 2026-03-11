"""Shared test fixtures for TDAD tests."""

import pytest
from pathlib import Path


@pytest.fixture
def sample_repo():
    """Path to the sample repository fixture."""
    return Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture
def sample_calculator(sample_repo):
    """Path to the calculator source file."""
    return sample_repo / "src" / "calculator.py"


@pytest.fixture
def sample_utils(sample_repo):
    """Path to the utils source file."""
    return sample_repo / "src" / "utils.py"


@pytest.fixture
def sample_test_calculator(sample_repo):
    """Path to the calculator test file."""
    return sample_repo / "tests" / "test_calculator.py"


@pytest.fixture
def sample_test_utils(sample_repo):
    """Path to the utils test file."""
    return sample_repo / "tests" / "test_utils.py"
