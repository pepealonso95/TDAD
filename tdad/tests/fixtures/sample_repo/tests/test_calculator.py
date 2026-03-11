"""Tests for the calculator module."""

from src.calculator import add, subtract, multiply, divide, Calculator


def test_add():
    assert add(2, 3) == 5


def test_subtract():
    assert subtract(5, 3) == 2


def test_multiply():
    assert multiply(4, 3) == 12


def test_divide():
    assert divide(10, 2) == 5.0


def test_divide_by_zero():
    try:
        divide(1, 0)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


class TestCalculator:
    def test_compute_add(self):
        calc = Calculator()
        assert calc.compute("add", 1, 2) == 3

    def test_last_result(self):
        calc = Calculator()
        calc.compute("multiply", 3, 4)
        assert calc.last_result() == 12

    def test_unknown_op(self):
        calc = Calculator()
        try:
            calc.compute("modulo", 1, 2)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
