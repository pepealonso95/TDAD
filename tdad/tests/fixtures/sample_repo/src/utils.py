"""Utility functions."""


def validate_number(value):
    """Ensure value is numeric."""
    if not isinstance(value, (int, float)):
        raise TypeError(f"Expected number, got {type(value).__name__}")
    return value


def clamp(value, minimum, maximum):
    """Clamp value to [minimum, maximum] range."""
    validate_number(value)
    validate_number(minimum)
    validate_number(maximum)
    return max(minimum, min(maximum, value))
