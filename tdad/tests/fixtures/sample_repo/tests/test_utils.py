"""Tests for the utils module."""

from src.utils import validate_number, clamp


def test_validate_number():
    assert validate_number(42) == 42
    assert validate_number(3.14) == 3.14


def test_validate_number_error():
    try:
        validate_number("not a number")
        assert False, "Should have raised TypeError"
    except TypeError:
        pass


def test_clamp():
    assert clamp(5, 0, 10) == 5
    assert clamp(-1, 0, 10) == 0
    assert clamp(15, 0, 10) == 10
