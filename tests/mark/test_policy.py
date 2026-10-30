from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from jarvis_local.models import ActionRequest, EmptyArguments, Reversibility, RiskLevel, ToolSpec
from jarvis_local.policy import PolicyEngine, PolicyViolation
from tests.mark.helpers import make_settings


def no_op(*_):
    return None


class PolicyTests(TestCase):
    def test_accepts_path_inside_project(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            policy = PolicyEngine(make_settings(root))
            self.assertEqual(
                policy.validate_path(root / "notes.txt", project_root=root),
                root / "notes.txt",
            )

    def test_rejects_path_outside_allowed_root(self) -> None:
        with TemporaryDirectory() as directory, TemporaryDirectory() as other:
            root = Path(directory).resolve()
            policy = PolicyEngine(make_settings(root))
            with self.assertRaises(PolicyViolation):
                policy.validate_path(Path(other) / "secret.txt", project_root=root)

    def test_rejects_denylisted_component_inside_project(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            policy = PolicyEngine(make_settings(root))
            with self.assertRaises(PolicyViolation):
                policy.validate_path(root / ".ssh" / "id_ed25519", project_root=root)

    def test_rejects_symbolic_link_that_resolves_outside_project(self) -> None:
        with TemporaryDirectory() as directory, TemporaryDirectory() as other:
            root = Path(directory).resolve()
            outside = Path(other).resolve() / "secret.txt"
            outside.write_text("secret", encoding="utf-8")
            link = root / "linked.txt"
            try:
                link.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"El entorno no permite crear enlaces simbólicos: {exc}")
            policy = PolicyEngine(make_settings(root))
            with self.assertRaises(PolicyViolation):
                policy.validate_path(link, project_root=root)

    def test_rejects_cross_project_path_even_if_globally_allowed(self) -> None:
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            first_root = Path(first).resolve()
            second_root = Path(second).resolve()
            settings = make_settings(first_root, allowed_roots=(first_root, second_root))
            policy = PolicyEngine(settings)
            with self.assertRaises(PolicyViolation):
                policy.validate_path(second_root / "other.txt", project_root=first_root)

    def test_rejects_unc_paths(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            policy = PolicyEngine(make_settings(root))
            with self.assertRaises(PolicyViolation):
                policy.validate_path(r"\\servidor\recurso\archivo.txt", project_root=root)

    def test_recalculates_external_effect_as_sensitive(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            policy = PolicyEngine(make_settings(root))
            spec = ToolSpec(
                name="get_current_time",
                description="test",
                argument_model=EmptyArguments,
                risk=RiskLevel.OBSERVE,
                handler=no_op,
                timeout_seconds=1,
                reversibility=Reversibility.IRREVERSIBLE,
                external_effect=True,
            )
            request = ActionRequest(
                tool=spec.name,
                arguments={},
                expected_result="resultado",
                project_id="project",
            )
            decision = policy.evaluate(request, spec, project_root=root)
            self.assertTrue(decision.allowed)
            self.assertTrue(decision.requires_confirmation)
            self.assertEqual(decision.calculated_risk, RiskLevel.SENSITIVE)

