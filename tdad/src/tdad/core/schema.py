"""Neo4j schema definitions: constraints and indexes for the TDAD graph."""

CONSTRAINTS = [
    "CREATE CONSTRAINT file_path IF NOT EXISTS FOR (f:File) REQUIRE f.path IS UNIQUE",
    "CREATE CONSTRAINT function_id IF NOT EXISTS FOR (fn:Function) REQUIRE fn.id IS UNIQUE",
    "CREATE CONSTRAINT class_id IF NOT EXISTS FOR (c:Class) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT test_id IF NOT EXISTS FOR (t:Test) REQUIRE t.id IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX file_name IF NOT EXISTS FOR (f:File) ON (f.name)",
    "CREATE INDEX function_name IF NOT EXISTS FOR (fn:Function) ON (fn.name)",
    "CREATE INDEX function_file IF NOT EXISTS FOR (fn:Function) ON (fn.file_path)",
    "CREATE INDEX function_qualified IF NOT EXISTS FOR (fn:Function) ON (fn.qualified_name)",
    "CREATE INDEX class_name IF NOT EXISTS FOR (c:Class) ON (c.name)",
    "CREATE INDEX class_file IF NOT EXISTS FOR (c:Class) ON (c.file_path)",
    "CREATE INDEX test_name IF NOT EXISTS FOR (t:Test) ON (t.name)",
    "CREATE INDEX test_file IF NOT EXISTS FOR (t:Test) ON (t.file_path)",
]
