import io
import os
import re
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from flake_conviction.cli import main

ROOT = Path(__file__).resolve().parents[1]
BLOCKED = ("import sys; sys.modules['solari_sandbox'] = None; sys.modules['crux'] = None\n"
           "from flake_conviction.cli import main\nraise SystemExit(main(sys.argv[1:]))")


class CliTests(unittest.TestCase):
    def test_attest_and_convict_exit_2_with_one_line_when_the_key_is_missing(self):
        for argv in (["attest", "--yes"], ["convict", "--yes"]):
            with patch.dict(os.environ, {}, clear=True), redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(argv), 2)
            self.assertEqual(len(out.getvalue().splitlines()), 1, argv)

    def test_help_and_key_check_do_not_import_the_sdk(self):
        env = {k: v for k, v in os.environ.items() if k != "SOLARI_API_KEY"}
        for argv, expected in ((["--help"], 0), (["attest", "--yes"], 2), (["convict"], 2)):
            done = subprocess.run([sys.executable, "-c", BLOCKED, *argv], env=env,
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, expected, done.stderr)
        self.assertIn("SOLARI_API_KEY", done.stdout)

    def test_reap_refuses_a_tag_that_is_not_ours(self):
        with patch.dict(os.environ, {}, clear=True), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(["reap", "crux-abc"]), 2)
        self.assertIn("fc- plus 12 hex", out.getvalue())

    def test_env_example_lists_exactly_the_variables_the_code_reads(self):
        declared = {line.split("=")[0] for line in (ROOT / ".env.example").read_text().splitlines()
                    if line and not line.startswith("#")}
        #  The fixture runs in the guest, where crux's factor specs set its variables.
        read = {name for path in (ROOT / "flake_conviction").glob("*.py")
                for name in re.findall(r'os\.environ(?:\.get\(|\[)"([A-Z_]+)"', path.read_text())}
        self.assertEqual(declared, read)
        self.assertEqual(declared, {"SOLARI_API_KEY"})


if __name__ == "__main__":
    unittest.main()
