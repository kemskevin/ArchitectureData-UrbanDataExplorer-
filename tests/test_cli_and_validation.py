from __future__ import annotations

import sys
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "pipeline" / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from urban_data_explorer import cli
from urban_data_explorer.validation import missing_items, validate_mapping_keys


class ValidationHelperTests(unittest.TestCase):
    def test_missing_items_preserves_required_order(self) -> None:
        self.assertEqual(missing_items(["b"], ["a", "b", "c"]), ["a", "c"])

    def test_validate_mapping_keys_formats_issues(self) -> None:
        issues = validate_mapping_keys("payload", {"a": 1}, ["a", "b"])
        self.assertEqual(issues, ["payload: cle manquante `b`"])


class CliTests(unittest.TestCase):
    def test_parser_exposes_run_and_validate_commands(self) -> None:
        parser = cli.build_parser()

        run_args = parser.parse_args(["run", "--skip-download", "--skip-build", "--skip-validate"])
        validate_args = parser.parse_args(["validate", "--quiet"])

        self.assertEqual(run_args.command, "run")
        self.assertEqual(validate_args.command, "validate")

    def test_run_orchestrates_enabled_steps(self) -> None:
        with (
            patch.object(cli, "cmd_download", return_value=0) as download,
            patch.object(cli, "cmd_build", return_value=0) as build,
            patch.object(cli, "cmd_validate", return_value=0) as validate,
            redirect_stdout(StringIO()),
        ):
            code = cli.cmd_run(
                ["dvf_2025_paris"],
                force_download=True,
                skip_download=False,
                skip_build=False,
                skip_validate=False,
                skip_noise=True,
            )

        self.assertEqual(code, 0)
        download.assert_called_once_with(["dvf_2025_paris"], True)
        build.assert_called_once_with(True)
        validate.assert_called_once_with()

    def test_validate_reports_unavailable_storage(self) -> None:
        with patch.object(cli, "validate_gold_outputs", side_effect=RuntimeError("db down")), redirect_stdout(StringIO()):
            code = cli.cmd_validate()

        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
