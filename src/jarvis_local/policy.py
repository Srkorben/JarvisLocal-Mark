from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import Settings
from .models import ActionRequest, PolicyDecision, Reversibility, RiskLevel, ToolSpec


class PolicyViolation(RuntimeError):
    pass


class PolicyEngine:
    POLICY_VERSION = "1"

    def __init__(self, settings: Settings):
        self.settings = settings

    @staticmethod
    def _is_within(candidate: Path, root: Path) -> bool:
        candidate_normalized = os.path.normcase(str(candidate.resolve()))
        root_normalized = os.path.normcase(str(root.resolve()))
        try:
            return os.path.commonpath([candidate_normalized, root_normalized]) == root_normalized
        except ValueError:
            return False

    @staticmethod
    def _is_within_lexically(candidate: Path, root: Path) -> bool:
        candidate_normalized = os.path.normcase(os.path.abspath(str(candidate)))
        root_normalized = os.path.normcase(os.path.abspath(str(root)))
        try:
            return os.path.commonpath([candidate_normalized, root_normalized]) == root_normalized
        except ValueError:
            return False

    @staticmethod
    def _is_reparse_point(path: Path) -> bool:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction and is_junction())

    def _reject_reparse_components(self, lexical: Path, roots: tuple[Path, ...]) -> None:
        for root in roots:
            if not self._is_within_lexically(lexical, root):
                continue
            relative = Path(os.path.relpath(lexical, root))
            current = root
            for part in relative.parts:
                current /= part
                if (current.exists() or current.is_symlink()) and self._is_reparse_point(current):
                    raise PolicyViolation(f"Ruta con enlace simbólico o junction no permitida: {current}")
            return

    def validate_path(self, raw_path: str | Path, *, project_root: Path | None = None) -> Path:
        if not str(raw_path).strip():
            raise PolicyViolation("La ruta no puede estar vacía.")
        expanded_text = os.path.expandvars(str(raw_path))
        if expanded_text.startswith(("\\\\", "//")):
            raise PolicyViolation("Las rutas UNC no están habilitadas.")
        lexical = Path(os.path.abspath(str(Path(expanded_text).expanduser())))
        candidate = lexical.resolve()
        folded_parts = {part.casefold() for part in candidate.parts}
        denied = folded_parts.intersection(self.settings.denied_path_parts)
        if denied:
            raise PolicyViolation(f"Ruta denegada por política: {sorted(denied)[0]}")

        if not any(self._is_within(candidate, root) for root in self.settings.allowed_roots):
            raise PolicyViolation(f"La ruta está fuera de las raíces autorizadas: {candidate}")
        if project_root is not None and not self._is_within(candidate, project_root):
            raise PolicyViolation(
                f"La ruta pertenece a otro contexto de proyecto: {candidate}"
            )
        roots_to_check = (
            (project_root.resolve(),)
            if project_root is not None
            else tuple(root.resolve() for root in self.settings.allowed_roots)
        )
        self._reject_reparse_components(lexical, roots_to_check)
        return candidate

    def _calculate_risk(self, spec: ToolSpec) -> RiskLevel:
        risk = spec.risk
        if spec.modifies_files and spec.reversibility in {
            Reversibility.PARTIAL,
            Reversibility.IRREVERSIBLE,
        }:
            risk = max(risk, RiskLevel.SENSITIVE)
        if spec.external_effect:
            risk = max(risk, RiskLevel.SENSITIVE)
        if spec.requires_elevation:
            risk = RiskLevel.PRIVILEGED
        return RiskLevel(risk)

    def evaluate(
        self,
        request: ActionRequest,
        spec: ToolSpec,
        *,
        project_root: Path,
    ) -> PolicyDecision:
        reasons: list[str] = []
        normalized = dict(request.arguments)
        calculated_risk = self._calculate_risk(spec)

        if request.tool != spec.name:
            return PolicyDecision(
                allowed=False,
                requires_confirmation=False,
                calculated_risk=RiskLevel.PRIVILEGED,
                reasons=("La herramienta solicitada no coincide con la especificación.",),
                normalized_arguments={},
                policy_version=self.POLICY_VERSION,
            )

        if spec.name not in self.settings.allowed_tools:
            reasons.append("La herramienta no está en la lista blanca.")

        for argument_name in spec.path_arguments:
            value = normalized.get(argument_name)
            if value is None:
                continue
            normalized[argument_name] = str(
                self.validate_path(str(value), project_root=project_root)
            )

        if spec.application_argument:
            raw_application = os.path.expandvars(
                str(normalized.get(spec.application_argument, ""))
            )
            if raw_application.startswith(("\\\\", "//")):
                reasons.append("No se permiten aplicaciones desde rutas UNC.")
            application_path = Path(raw_application).expanduser()
            if not application_path.is_absolute():
                reasons.append("La aplicación debe identificarse mediante una ruta absoluta.")
            application = os.path.normcase(str(application_path.resolve()))
            allowed_applications = {
                os.path.normcase(str(Path(os.path.expandvars(value)).expanduser().resolve()))
                for value in self.settings.allowed_applications
            }
            if application not in allowed_applications:
                reasons.append("La aplicación no está en la lista blanca.")
            else:
                normalized[spec.application_argument] = str(application_path.resolve())

        if spec.domain_argument:
            raw_destination = str(normalized.get(spec.domain_argument, ""))
            hostname = (urlparse(raw_destination).hostname or raw_destination).casefold()
            if hostname not in self.settings.allowed_domains:
                reasons.append("El dominio no está en la lista blanca.")

        if calculated_risk == RiskLevel.PRIVILEGED and not self.settings.privileged_tools_enabled:
            reasons.append("Las herramientas privilegiadas están deshabilitadas.")

        allowed = not reasons
        requires_confirmation = allowed and int(calculated_risk) > self.settings.auto_approve_max_risk
        if allowed:
            reasons.append(f"Riesgo recalculado por política: nivel {int(calculated_risk)}.")

        return PolicyDecision(
            allowed=allowed,
            requires_confirmation=requires_confirmation,
            calculated_risk=calculated_risk,
            reasons=tuple(reasons),
            normalized_arguments=normalized,
            policy_version=self.POLICY_VERSION,
        )

