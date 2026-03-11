"""Tests for the AST parser module."""

from pathlib import Path

from tdad.indexer.ast_parser import (
    FileInfo,
    FunctionInfo,
    ClassInfo,
    parse_file,
    is_test_file,
    is_test_function,
    is_test_class,
)


def test_is_test_file():
    assert is_test_file("test_foo.py")
    assert is_test_file("foo_test.py")
    assert is_test_file("tests.py")
    assert not is_test_file("foo.py")
    assert not is_test_file("testing.py")


def test_is_test_function():
    assert is_test_function("test_add")
    assert is_test_function("test_")
    assert not is_test_function("add")
    assert not is_test_function("testing_add")


def test_is_test_class():
    assert is_test_class("TestCalculator")
    assert is_test_class("Test")
    assert not is_test_class("Calculator")
    # Note: "Tester" matches "Test*" — this is by design (fnmatch)
    assert is_test_class("Tester")


def test_parse_calculator(sample_repo, sample_calculator):
    info = parse_file(sample_calculator, sample_repo)

    assert isinstance(info, FileInfo)
    assert info.name == "calculator.py"
    assert not info.is_test_file
    assert info.content_hash  # non-empty

    # Should find top-level functions: add, subtract, multiply, divide
    func_names = [f.name for f in info.functions]
    assert "add" in func_names
    assert "subtract" in func_names
    assert "multiply" in func_names
    assert "divide" in func_names

    # Should find Calculator class
    class_names = [c.name for c in info.classes]
    assert "Calculator" in class_names

    # Calculator should have methods
    calc_class = next(c for c in info.classes if c.name == "Calculator")
    method_names = [m.name for m in calc_class.methods]
    assert "__init__" in method_names
    assert "compute" in method_names
    assert "last_result" in method_names

    # Should detect imports
    assert "utils" in info.imports or ".utils" in info.imports


def test_parse_test_file(sample_repo, sample_test_calculator):
    info = parse_file(sample_test_calculator, sample_repo)

    assert info.is_test_file
    assert info.name == "test_calculator.py"

    # Should find test functions
    func_names = [f.name for f in info.functions]
    assert "test_add" in func_names
    assert "test_subtract" in func_names
    assert "test_divide_by_zero" in func_names

    # Test functions should be marked as tests
    for func in info.functions:
        assert func.is_test

    # Should find TestCalculator class
    class_names = [c.name for c in info.classes]
    assert "TestCalculator" in class_names


def test_parse_utils(sample_repo, sample_utils):
    info = parse_file(sample_utils, sample_repo)

    assert not info.is_test_file
    func_names = [f.name for f in info.functions]
    assert "validate_number" in func_names
    assert "clamp" in func_names

    # clamp should call validate_number
    clamp_func = next(f for f in info.functions if f.name == "clamp")
    assert "validate_number" in clamp_func.calls


def test_parse_syntax_error(sample_repo, tmp_path):
    """Parsing a file with syntax errors returns empty FileInfo."""
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("def broken(:\n  pass")

    info = parse_file(bad_file, tmp_path)
    assert info.functions == []
    assert info.classes == []


def test_function_info_fields(sample_repo, sample_calculator):
    info = parse_file(sample_calculator, sample_repo)
    add_func = next(f for f in info.functions if f.name == "add")

    assert add_func.start_line > 0
    assert add_func.end_line >= add_func.start_line
    assert "add(" in add_func.signature
    assert add_func.docstring is not None
    assert not add_func.is_test
