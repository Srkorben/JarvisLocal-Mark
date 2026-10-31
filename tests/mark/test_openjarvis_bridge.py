import json
import tempfile
import tomllib
import unittest
from pathlib import Path

from jarvis_local.openjarvis_bridge import (
    capability_policy,
    openjarvis_environment,
    prepare_openjarvis_home,
)
from tests.mark.helpers import make_settings


def _agent(policy, agent_id):
    return next(item for item in policy["agents"] if item["agent_id"] == agent_id)


class OpenJarvisBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_policy_mirrors_mark_denials(self):
        policy = capability_policy(make_settings(self.root))
        agents = _agent(policy, "_default")
        granted = {grant["capability"] for grant in agents["grants"]}
        self.assertEqual(
            granted, {"memory:read", "memory:write", "schedule:create", "file:read"}
        )
        self.assertEqual(
            set(agents["deny"]),
            {
                "file:write",
                "code:execute",
                "network:fetch",
                "channel:send",
                "tool:invoke",
                "system:admin",
            },
        )
        admin = _agent(policy, "server:api")
        self.assertIn({"capability": "system:admin"}, admin["grants"])

    def test_policy_follows_mark_permissions(self):
        settings = make_settings(
            self.root,
            allowed_domains=frozenset({"example.com"}),
            max_outbound_bytes=4096,
            privileged_tools_enabled=True,
        )
        agents = _agent(capability_policy(settings), "_default")
        granted = {grant["capability"] for grant in agents["grants"]}
        self.assertTrue({"network:fetch", "code:execute", "tool:invoke"} <= granted)
        self.assertNotIn("network:fetch", agents["deny"])
        # Dominios sin presupuesto de salida no abren la red.
        closed = make_settings(self.root, allowed_domains=frozenset({"example.com"}))
        self.assertIn("network:fetch", _agent(capability_policy(closed), "_default")["deny"])

    def test_home_keeps_user_settings_but_enforces_security(self):
        settings = make_settings(
            self.root, model_provider="openjarvis", model="qwen3:8b", openjarvis_engine="ollama"
        )
        home = settings.data_dir / "openjarvis"
        home.mkdir(parents=True)
        (home / "config.toml").write_text(
            '[security]\ncapabilities = { enabled = false }\nmode = "warn"\n'
            '[channel]\ndefault_agent = "simple"\n',
            encoding="utf-8",
        )
        self.assertEqual(prepare_openjarvis_home(settings), home)
        config = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
        self.assertEqual(config["channel"], {"default_agent": "simple"})
        self.assertEqual(config["security"]["mode"], "warn")
        caps = config["security"]["capabilities"]
        self.assertEqual(caps["enabled"], True)
        self.assertEqual(caps["default_deny"], True)
        self.assertEqual(caps["policy_path"], str(home / "capabilities.json"))
        self.assertEqual(
            config["security"]["allowed_dirs"],
            [str(root) for root in settings.allowed_roots],
        )
        self.assertEqual(config["server"], {"host": "127.0.0.1", "port": 8790})
        self.assertEqual(config["analytics"]["enabled"], False)
        self.assertEqual(config["intelligence"]["default_model"], "qwen3:8b")
        self.assertEqual(config["engine"]["default"], "ollama")
        self.assertEqual(config["speech"]["tts_backend"], "mark_voice")
        policy = json.loads((home / "capabilities.json").read_text(encoding="utf-8"))
        self.assertEqual(policy, capability_policy(settings))

    def test_policy_file_loads_in_openjarvis(self):
        from openjarvis.security.capabilities import CapabilityPolicy

        home = prepare_openjarvis_home(make_settings(self.root))
        policy = CapabilityPolicy(
            policy_path=str(home / "capabilities.json"), default_deny=True
        )
        self.assertTrue(policy.check("any-agent", "file:read", "file_read"))
        self.assertTrue(policy.check("any-agent", "memory:write", "kg_add_entity"))
        self.assertFalse(policy.check("any-agent", "file:write", "file_write"))
        self.assertFalse(policy.check("any-agent", "code:execute", "shell_exec"))
        self.assertFalse(policy.check("any-agent", "network:fetch", "http_request"))
        self.assertFalse(policy.check("any-agent", "system:admin", "agent_spawn"))
        self.assertTrue(policy.check("server:api", "system:admin", "agent_list"))

    def test_environment_matches_mark_context(self):
        settings = make_settings(self.root, context_tokens=8192)
        env = dict(openjarvis_environment(settings, self.root / "oj"))
        self.assertEqual(env["OPENJARVIS_HOME"], str(self.root / "oj"))
        self.assertEqual(env["JARVIS_NUM_CTX"], "8192")
        self.assertEqual(env["OPENJARVIS_FRAME_ANCESTORS"], "http://127.0.0.1:*")


if __name__ == "__main__":
    unittest.main()
