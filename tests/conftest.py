"""Shared fixtures for the md_tools test suite."""

import pytest

import md_tools_backup


@pytest.fixture(autouse=True)
def reset_backed_up():
    """Clear the per-invocation backup dedup set before each test."""
    md_tools_backup._backed_up.clear()
