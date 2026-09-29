"""Tests for the triage CLI: run/eval subcommands, dispatcher seam, hygiene."""
from __future__ import annotations

import builtins
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

DATA_PATH = "data/synthetic/support_tickets_synth_v1.jsonl"
_ALLOWED_KEYS = {"ticket_id", "route", "priority", "confidence", "disposition", "reasons"}
_SECRET_TOKEN = "hunter2-synth"
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str, cwd: str, env: dict | None = None) -> subprocess.CompletedProcess:
    run_env = None
    if env is not None:
        import os

        run_env = {**os.environ, **env}
    return subprocess.run(
        ["uv", "run", "triage", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=run_env,
    )


class TestCliModuleImportHygiene(unittest.TestCase):
    def test_cli_module_does_not_import_crewai_at_module_scope(self):
        """Importing triage_router.cli must not pull in crewai eagerly.

        This test is only meaningful when run in an environment where crewai IS
        installed; it proves the lazy-import discipline rather than a false
        negative from a missing dependency.
        """
        for mod in list(sys.modules):
            if mod == "crewai" or mod.startswith("crewai."):
                del sys.modules[mod]
        sys.modules.pop("triage_router.cli", None)

        import triage_router.cli  # noqa: F401

        self.assertNotIn("crewai", sys.modules)


class TestCliRun(unittest.TestCase):
    def setUp(self):
        self._tmpdir_ctx = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir_ctx.name)
        self.addCleanup(self._tmpdir_ctx.cleanup)

    def test_run_fake_provider_over_full_dataset(self):
        out_path = self.tmp_path / "decisions.jsonl"
        repo_root = str(_REPO_ROOT)
        result = _run_cli(
            "run",
            "--tickets",
            DATA_PATH,
            "--provider",
            "fake",
            "--out",
            str(out_path),
            cwd=repo_root,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        lines = out_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 24)

        dispatch_count = 0
        review_count = 0
        for line in lines:
            record = json.loads(line)
            self.assertLessEqual(set(record.keys()), _ALLOWED_KEYS)
            self.assertIn("ticket_id", record)
            self.assertIn("disposition", record)
            if record["disposition"] == "dispatch":
                dispatch_count += 1
            elif record["disposition"] == "review":
                review_count += 1

        self.assertEqual(dispatch_count + review_count, 24)

        # Summary printed to stdout must mention counts by route and
        # dispatch/review breakdown.
        self.assertIn("dispatch", result.stdout.lower())
        self.assertIn("review", result.stdout.lower())

    def test_run_output_and_stdout_never_leak_raw_secret_or_expected(self):
        out_path = self.tmp_path / "decisions.jsonl"
        repo_root = str(_REPO_ROOT)
        result = _run_cli(
            "run",
            "--tickets",
            DATA_PATH,
            "--provider",
            "fake",
            "--out",
            str(out_path),
            cwd=repo_root,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        out_text = out_path.read_text(encoding="utf-8")
        self.assertNotIn(_SECRET_TOKEN, out_text)
        self.assertNotIn("expected", out_text)

        self.assertNotIn(_SECRET_TOKEN, result.stdout)
        self.assertNotIn("expected", result.stdout)
        self.assertNotIn(_SECRET_TOKEN, result.stderr)

    def test_dispatch_without_crewai_fails_cleanly(self):
        """Simulate crewai not being importable: the lazy `from .dispatch import
        dispatch` inside the run handler must raise/exit cleanly with a clear
        message rather than crash uninformatively, and must never be imported
        unless --dispatch is passed."""
        from triage_router import cli

        tickets_path = self.tmp_path / "tickets.jsonl"
        tickets_path.write_text(
            json.dumps({"ticket_id": "TCK-TEST", "subject": "s", "body": "b"}) + "\n",
            encoding="utf-8",
        )

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name in ("triage_router.dispatch", ".dispatch", "dispatch"):
                raise ImportError("simulated: crewai not importable")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", _fake_import), self.assertRaises(SystemExit) as ctx:
            cli.main(
                [
                    "run",
                    "--tickets",
                    str(tickets_path),
                    "--provider",
                    "fake",
                    "--dispatch",
                ]
            )
        self.assertNotEqual(ctx.exception.code, 0)

    def test_live_provider_without_key_fails_fast_before_processing(self):
        """--provider live with OPENROUTER_API_KEY unset must exit non-zero
        with an actionable message BEFORE any ticket is processed: no --out
        file is written (or it stays empty/nonexistent)."""
        out_path = self.tmp_path / "decisions.jsonl"
        repo_root = str(_REPO_ROOT)
        env = dict(__import__("os").environ)
        env.pop("OPENROUTER_API_KEY", None)
        result = _run_cli(
            "run",
            "--tickets",
            DATA_PATH,
            "--provider",
            "live",
            "--out",
            str(out_path),
            cwd=repo_root,
            env=env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OPENROUTER_API_KEY", result.stderr)
        self.assertFalse(out_path.exists())

    def test_eval_stub_exits_zero(self):
        from triage_router import cli

        decisions_path = self.tmp_path / "decisions.jsonl"
        decisions_path.write_text(
            json.dumps({"ticket_id": "TCK-1", "route": "faq", "priority": "low",
                         "confidence": 0.9, "disposition": "dispatch", "reasons": []})
            + "\n",
            encoding="utf-8",
        )

        with self.assertRaises(SystemExit) as ctx:
            cli.main(["eval", "--decisions", str(decisions_path)])
        self.assertEqual(ctx.exception.code, 0)

    def test_eval_missing_decisions_file_actionable_error(self):
        missing_path = self.tmp_path / "nope.jsonl"
        result = _run_cli(
            "eval",
            "--decisions",
            str(missing_path),
            "--tickets",
            DATA_PATH,
            cwd=str(_REPO_ROOT),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("decisions file not found", result.stderr)
        self.assertIn(str(missing_path), result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_eval_missing_tickets_file_actionable_error(self):
        decisions_path = self.tmp_path / "decisions.jsonl"
        decisions_path.write_text("", encoding="utf-8")
        missing_tickets = self.tmp_path / "no_tickets.jsonl"
        result = _run_cli(
            "eval",
            "--decisions",
            str(decisions_path),
            "--tickets",
            str(missing_tickets),
            cwd=str(_REPO_ROOT),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tickets file not found", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_eval_malformed_decisions_jsonl_actionable_error(self):
        decisions_path = self.tmp_path / "decisions.jsonl"
        decisions_path.write_text("not json\n", encoding="utf-8")
        result = _run_cli(
            "eval",
            "--decisions",
            str(decisions_path),
            "--tickets",
            DATA_PATH,
            cwd=str(_REPO_ROOT),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("malformed JSONL at line 1", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_eval_malformed_tickets_jsonl_actionable_error(self):
        decisions_path = self.tmp_path / "decisions.jsonl"
        decisions_path.write_text("", encoding="utf-8")
        tickets_path = self.tmp_path / "tickets.jsonl"
        tickets_path.write_text("not json\n", encoding="utf-8")
        result = _run_cli(
            "eval",
            "--decisions",
            str(decisions_path),
            "--tickets",
            str(tickets_path),
            cwd=str(_REPO_ROOT),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("line 1", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
