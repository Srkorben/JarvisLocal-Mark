from __future__ import annotations

from pathlib import Path

from .database import Database
from .models import ProjectRecord, ProjectStatus
from .policy import PolicyEngine


class ProjectService:
    """Mantiene identidad explícita y evita mezclar contexto entre proyectos."""

    def __init__(self, database: Database, policy: PolicyEngine):
        self.database = database
        self.policy = policy

    def ensure_bootstrap_project(self, name: str, root_path: Path) -> ProjectRecord:
        validated_root = self.policy.validate_path(root_path)
        for project in self.database.list_projects():
            if Path(project.root_path) == validated_root:
                if self.database.get_active_project() is None:
                    return self.database.set_active_project(project.id)
                return project
        return self.database.create_project(name, validated_root, make_active=True)

    def create(
        self,
        name: str,
        root_path: Path,
        *,
        make_active: bool = False,
        config: dict | None = None,
        permissions: dict[str, bool] | None = None,
    ) -> ProjectRecord:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("El nombre del proyecto no puede estar vacío.")
        validated_root = self.policy.validate_path(root_path)
        if not validated_root.is_dir():
            raise NotADirectoryError(validated_root)
        return self.database.create_project(
            normalized_name,
            validated_root,
            make_active=make_active,
            config=config,
            permissions=permissions,
        )

    def active(self) -> ProjectRecord | None:
        return self.database.get_active_project()

    def activate(self, project_id: str) -> ProjectRecord:
        project = self.validate_action_project(project_id)
        return self.database.set_active_project(project.id)

    def set_permission(
        self, project_id: str, permission: str, enabled: bool
    ) -> ProjectRecord:
        allowed = {"read", "index", "memory", "open", "execute", "write"}
        normalized = permission.strip().casefold()
        if normalized not in allowed:
            raise ValueError(f"Permiso de proyecto no soportado: {permission}")
        self.database.get_project(project_id)
        return self.database.set_project_permission(project_id, normalized, enabled)

    def list(self) -> list[ProjectRecord]:
        return self.database.list_projects()

    def validate_action_project(self, project_id: str | None) -> ProjectRecord:
        if not project_id:
            raise ValueError("Toda acción debe pertenecer a un proyecto explícito.")
        project = self.database.get_project(project_id)
        if project.status != ProjectStatus.ENABLED:
            raise ValueError(f"El proyecto no está habilitado: {project.name}")
        self.policy.validate_path(project.root_path)
        return project

    def require_permission(self, project: ProjectRecord, permission: str) -> None:
        # Los proyectos migrados desde Fase 0 no tenían mapa explícito; las tres
        # capacidades de lectura conservan el comportamiento previo.
        default = permission in {"read", "index", "memory"}
        if not bool(project.permissions.get(permission, default)):
            raise PermissionError(
                f"El proyecto {project.name} no autoriza la capacidad {permission!r}."
            )

