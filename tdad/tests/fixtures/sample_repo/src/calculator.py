"""Simple calculator module for testing."""

from .utils import validate_number


def add(a, b):
    """Add two numbers."""
    validate_number(a)
    validate_number(b)
    return a + b


def subtract(a, b):
    """Subtract b from a."""
    validate_number(a)
    validate_number(b)
    return a - b


def multiply(a, b):
    """Multiply two numbers."""
    validate_number(a)
    validate_number(b)
    return a * b


def divide(a, b):
    """Divide a by b."""
    validate_number(a)
    validate_number(b)
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


class Calculator:
    """Stateful calculator with history."""

    def __init__(self):
        self.history = []

    def compute(self, op, a, b):
        ops = {"add": add, "subtract": subtract, "multiply": multiply, "divide": divide}
        if op not in ops:
            raise ValueError(f"Unknown operation: {op}")
        result = ops[op](a, b)
        self.history.append((op, a, b, result))
        return result

    def last_result(self):
        if not self.history:
            return None
        return self.history[-1][3]
