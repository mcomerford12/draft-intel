"""Project tooling that is not shipped in the package but is imported by tests.

A package rather than loose scripts so `tools.rehearsal` has one module name. Without it mypy
sees the same file as both `rehearsal` and `tools.rehearsal` and refuses to check either.
"""
