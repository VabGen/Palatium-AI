# src/palatium_ai/domain/projects/errors.py

"""Typed project domain errors (035)."""

from __future__ import annotations


class ProjectError(Exception):
    """Base project-domain failure."""


class ProjectNotFoundError(ProjectError):
    """Requested project does not exist for the caller."""


class ProjectOwnershipError(ProjectError):
    """Caller may not mutate or pin this project."""
