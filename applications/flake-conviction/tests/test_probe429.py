import asyncio
import io
import os
import re
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from flake_conviction.cli import main
from flake_conviction.probe429 import count_offline


class Probe429Tests(unittest.TestCase):
    def test_offline_create_is_retried_against_a_retryable_429(self):
        with patch.dict(os.environ, {}, clear=True), redirect_stdout(io.StringIO()) as out:
            code = main(["probe-429"])
        attempts = int(re.search(r"create   retryable 429: (\d+) HTTP attempts", out.getvalue())[1])
        #  Printed, not asserted, so a changed retry count fails below for the right reason.
        print(f"create() against a retryable 429: {attempts} attempts")
        self.assertGreater(attempts, 1)
        self.assertIn("raised ConcurrencyLimitError", out.getvalue())
        self.assertEqual(code, 0)

    def test_offline_non_idempotent_post_is_sent_once(self):
        attempts, _, raised = asyncio.run(
            count_offline(lambda c: c.promote_snapshot("snap-offline", "offline")))
        self.assertEqual((attempts, raised), (1, "ConcurrencyLimitError"))


if __name__ == "__main__":
    unittest.main()
