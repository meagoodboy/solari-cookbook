import asyncio
import unittest

from fake_solari import FakeClient
from flake_conviction.attest import attest
from flake_conviction.session import EXPECTED_PATH, Redactor

TAG = "fc-0123456789ab"


def run_attest(fake, clones=3):
    lines = []
    code = asyncio.run(attest(fake, clones=clones, say=lines.append, redactor=Redactor(), run_tag=TAG))
    return code, lines


def rows(lines):
    return [w for w in map(str.split, lines) if w[0].isdigit() and w[1].startswith("sbx-")]


def line_starting(lines, word):
    return next(line for line in lines if line.startswith(word))


class AttestTests(unittest.TestCase):
    def test_every_clone_restores_the_base_digest(self):
        fake = FakeClient()
        code, lines = run_attest(fake)
        self.assertEqual(code, 0)
        self.assertEqual([row[2] for row in rows(lines)], ["yes", "yes", "yes"])
        self.assertEqual(len(fake.records), 4)
        self.assertEqual(fake.alive(), [])
        self.assertEqual(fake.snapshots, {})
        self.assertIn("after    sandboxes 0 (this run 0)   snapshots 0", lines[-1])

    def test_a_later_clone_restores_the_snapshot_not_the_previous_clone(self):
        fake = FakeClient()
        code, lines = run_attest(fake, clones=2)
        first, second = [r for r in fake.records.values() if r.metadata["role"] == "clone"]
        self.assertEqual(first.files[EXPECTED_PATH], b"overwritten by clone 1\n")
        self.assertEqual(rows(lines)[1][2:4], ["yes", line_starting(lines, "base").split()[-1]])
        self.assertEqual(second.files[EXPECTED_PATH], b"overwritten by clone 2\n")

    def test_a_corrupted_clone_is_refused_not_scored(self):
        fake = FakeClient(corrupt_clone=2)
        code, lines = run_attest(fake)
        self.assertEqual(code, 1)
        self.assertEqual([row[2] for row in rows(lines)], ["yes", "no", "yes"])
        self.assertEqual(fake.alive(), [])
        self.assertIn("sweep    killed 0 with this tag", lines[-2])

    def test_a_failed_create_still_reaps_base_and_snapshot(self):
        fake = FakeClient(fail_create_at=3)
        code, lines = run_attest(fake)
        self.assertEqual(code, 3)
        self.assertIn("failed   ConcurrencyLimitError", line_starting(lines, "failed"))
        self.assertEqual(fake.alive(), [])
        self.assertEqual(fake.snapshots, {})
        self.assertTrue(lines[-1].startswith("after    sandboxes 0"))

    def test_an_orphan_carrying_our_tag_is_reaped_by_the_sweep(self):
        fake = FakeClient(orphan_create_at=3)
        code, lines = run_attest(fake)
        self.assertEqual(code, 3)
        self.assertEqual(fake.alive(), [])
        self.assertIn("killed 1 with this tag (1 beyond the ledger)", line_starting(lines, "sweep"))
        self.assertIn("(this run 0)", lines[-1])

    def test_a_kill_that_raises_in_the_sweep_is_counted_and_the_census_still_prints(self):
        fake = FakeClient(orphan_create_at=3, kill_raises_at=3)  # kill 3 is the orphan's, swept
        code, lines = run_attest(fake)
        self.assertEqual(code, 3)
        self.assertIn("1 kill or delete calls failed", line_starting(lines, "sweep"))
        self.assertIn("after    sandboxes 1 (this run 1)", lines[-1])
        self.assertEqual(len(fake.alive()), 1)
        self.assertNotIn("sbx_", "\n".join(lines))

    def test_the_sweep_never_kills_a_sandbox_the_filter_leaked(self):
        fake = FakeClient(leak_foreign=True)
        code, lines = run_attest(fake)
        self.assertEqual(code, 0)
        foreign = next(r for r in fake.records.values() if r.foreign)
        self.assertEqual(foreign.state, "running")
        self.assertIn("1 filter leaks", line_starting(lines, "sweep"))
        self.assertIn("after    sandboxes 1 (this run 0)", lines[-1])

    def test_output_carries_no_raw_identifier(self):
        _, lines = run_attest(FakeClient())
        text = "\n".join(lines)
        self.assertNotIn("sbx_", text)
        self.assertNotIn("snap_", text)
        same = Redactor()
        self.assertEqual(same.ref("sbx_x", "sbx"), same.ref("sbx_x", "sbx"))
        self.assertNotEqual(same.ref("sbx_x", "sbx"), Redactor().ref("sbx_x", "sbx"))


if __name__ == "__main__":
    unittest.main()
