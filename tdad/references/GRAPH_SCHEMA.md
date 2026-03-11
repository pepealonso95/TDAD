# TDAD Graph Schema

## Node Types

### File
Represents a Python source file.

| Property | Type | Description |
|----------|------|-------------|
| `path` | string (unique) | Repo-relative file path |
| `name` | string | Filename |
| `content_hash` | string | MD5 of file content |
| `repo_path` | string | Absolute repo root path |
| `updated_at` | datetime | Last index time |

### Function
Represents a function or method.

| Property | Type | Description |
|----------|------|-------------|
| `id` | string (unique) | `{relative_path}::{name}:{start_line}` |
| `name` | string | Function name (or `Class.method`) |
| `file_path` | string | Repo-relative file path |
| `start_line` | int | First line number |
| `end_line` | int | Last line number |
| `signature` | string | Function signature |
| `docstring` | string | Docstring (if any) |
| `qualified_name` | string | `module.name` |

### Class
Represents a class definition.

| Property | Type | Description |
|----------|------|-------------|
| `id` | string (unique) | `{relative_path}::{name}:{start_line}` |
| `name` | string | Class name |
| `file_path` | string | Repo-relative file path |
| `start_line` | int | First line number |
| `end_line` | int | Last line number |
| `docstring` | string | Docstring (if any) |
| `qualified_name` | string | `module.Class` |

### Test
Represents a test function/method.

| Property | Type | Description |
|----------|------|-------------|
| `id` | string (unique) | `test::{function_id}` |
| `name` | string | Test function name |
| `file_path` | string | Repo-relative file path |

## Edge Types

### CONTAINS
`(File)-[:CONTAINS]->(Function|Class|Test)`

A file contains a function, class, or test.

### CALLS
`(Function)-[:CALLS]->(Function)`

A function calls another function. Resolved by name matching during indexing.

### IMPORTS
`(File)-[:IMPORTS]->(File)`

A file imports another file's module.

### INHERITS
`(Class)-[:INHERITS]->(Class)`

A class inherits from another class.

### TESTS
`(Test)-[:TESTS]->(Function|Class)`

A test tests a function or class. Created by the test linker with confidence scores.

| Property | Type | Description |
|----------|------|-------------|
| `link_source` | string | `naming`, `static`, `static_import`, `coverage` |
| `link_confidence` | float | 0.0–1.0 confidence score |

## Constraints & Indexes

```cypher
-- Constraints (uniqueness)
CREATE CONSTRAINT file_path FOR (f:File) REQUIRE f.path IS UNIQUE
CREATE CONSTRAINT function_id FOR (fn:Function) REQUIRE fn.id IS UNIQUE
CREATE CONSTRAINT class_id FOR (c:Class) REQUIRE c.id IS UNIQUE
CREATE CONSTRAINT test_id FOR (t:Test) REQUIRE t.id IS UNIQUE

-- Indexes (query performance)
CREATE INDEX FOR (f:File) ON (f.name)
CREATE INDEX FOR (fn:Function) ON (fn.name)
CREATE INDEX FOR (fn:Function) ON (fn.file_path)
CREATE INDEX FOR (fn:Function) ON (fn.qualified_name)
CREATE INDEX FOR (c:Class) ON (c.name)
CREATE INDEX FOR (c:Class) ON (c.file_path)
CREATE INDEX FOR (t:Test) ON (t.name)
CREATE INDEX FOR (t:Test) ON (t.file_path)
```
