"""The doctor must catch the install failures that are otherwise silent."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from test_support import PLUGIN_ROOT, load_module

doctor = load_module("scripts/doctor.py", "doctor")
install_target = load_module("scripts/install_target.py", "install_target_for_doctor")


def statuses(report: dict) -> dict[str, str]:
    return {item["check"]: item["status"] for item in report["findings"]}


class DoctorTests(unittest.TestCase):
    def install(self, host: str, workspace: Path) -> Path:
        with contextlib.redirect_stdout(io.StringIO()):
            install_target.install(host, workspace, dry_run=False)
        shared = ".github" if host == "vscode" else ".agents"
        return workspace / shared / "ae-toolkit" / "scripts" / "doctor.py"

    def test_the_source_checkout_passes_and_proves_both_gates(self) -> None:
        report = doctor.diagnose(PLUGIN_ROOT / "scripts" / "doctor.py", PLUGIN_ROOT)
        self.assertEqual("cursor", report["install"])
        self.assertTrue(report["ok"], report)
        found = statuses(report)
        self.assertEqual("pass", found["shell gate"])
        self.assertEqual("pass", found["MCP gate"])

    def test_an_installed_target_passes_on_every_host(self) -> None:
        for host in ("vscode", "antigravity"):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as tmp:
                workspace = Path(tmp).resolve()
                script = self.install(host, workspace)
                report = doctor.diagnose(script, workspace)
                self.assertEqual(host, report["install"])
                self.assertTrue(report["ok"], report)
                self.assertEqual("pass", statuses(report)["hook paths"])

    def test_relative_hook_paths_fail_where_the_host_fails_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve()
            shutil.copytree(PLUGIN_ROOT / "dist" / "antigravity", workspace, dirs_exist_ok=True)
            report = doctor.diagnose(workspace / ".agents" / "ae-toolkit" / "scripts" / "doctor.py", workspace)
            self.assertFalse(report["ok"])
            self.assertEqual("fail", statuses(report)["hook paths"])

    def test_a_missing_hook_config_means_no_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve()
            script = self.install("vscode", workspace)
            (workspace / ".github" / "hooks" / "ae-toolkit.json").unlink()
            report = doctor.diagnose(script, workspace)
            self.assertFalse(report["ok"])
            self.assertEqual("fail", statuses(report)["hook config"])

    def test_a_gate_that_allows_the_canary_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve()
            script = self.install("vscode", workspace)
            gate = workspace / ".github" / "ae-toolkit" / "hooks" / "safety_gate.py"
            gate.write_text(
                "import json\nprint(json.dumps({'hookSpecificOutput': {'permissionDecision': 'allow'}}))\n",
                encoding="utf-8",
            )
            report = doctor.diagnose(script, workspace)
            self.assertFalse(report["ok"])
            self.assertEqual("fail", statuses(report)["shell gate"])

    def test_a_missing_interpreter_is_reported_before_anything_else_matters(self) -> None:
        finding = doctor.check_hook_interpreter("python3-that-does-not-exist", "the hooks")
        self.assertEqual("fail", finding["status"])
        self.assertIn("not on PATH", finding["detail"])

    def test_a_symlinked_cursor_plugin_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            local = home / ".cursor" / "plugins" / "local"
            local.mkdir(parents=True)
            link = local / doctor.PLUGIN_NAME
            os.symlink(PLUGIN_ROOT, link, target_is_directory=True)
            original = Path.home
            Path.home = classmethod(lambda cls: home)  # type: ignore[assignment]
            try:
                findings = doctor.check_cursor_install(link / "scripts" / "doctor.py", PLUGIN_ROOT)
            finally:
                Path.home = original  # type: ignore[assignment]
            self.assertEqual("fail", findings[-1]["status"])
            self.assertIn("symlink", findings[-1]["detail"])

    def test_json_output_is_machine_readable(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = doctor.main(["--workspace", str(PLUGIN_ROOT), "--json"])
        self.assertEqual(0, code)
        self.assertIn("findings", json.loads(buffer.getvalue()))


if __name__ == "__main__":
    unittest.main()
