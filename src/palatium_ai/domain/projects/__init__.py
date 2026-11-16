# src/palatium_ai/domain/projects/__init__.py

"""First-class Projects (session pin + attachment KB scope id)."""

from palatium_ai.domain.projects.errors import (
    ProjectError,
    ProjectNotFoundError,
    ProjectOwnershipError,
)
from palatium_ai.domain.projects.models import ProjectRecord
from palatium_ai.domain.projects.ports import ProjectStore

__all__ = [
    "ProjectError",
    "ProjectNotFoundError",
    "ProjectOwnershipError",
    "ProjectRecord",
    "ProjectStore",
]
