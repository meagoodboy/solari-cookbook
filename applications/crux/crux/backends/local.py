"""Local worlds: pure Python simulators that honour the World protocol.

LocalWorld runs the invoice fixture and is the demo backend. The other
two exist to calibrate the statistics. NoEffectWorld fails at a flat
rate no factor can move. ConjunctionWorld only recovers when a specific
pair of factors is neutralized in the same branch.
"""

from __future__ import annotations

import random
from typing import Any

from .. import fixture
from ..models import RawRun

_SNAPSHOT = "local-0"


class LocalWorld:
    """Deterministic world over the invoice fixture.

    snapshot() is a fixed ref because the whole world is rebuilt from the
    trial seed. Two calls with the same assignment and seed return the
    same RawRun, field for field.

    large_invoice_p is passed through to the invoice generator. Leaving
    it at None keeps the fixture default, which is what the demo and the
    calibration tests use. The benchmark's weak-cause family lowers it
    so the layout bug fires on fewer trials.
    """

    def __init__(self, large_invoice_p: float | None = None) -> None:
        self._large_invoice_p = (
            fixture.LARGE_INVOICE_P if large_invoice_p is None else large_invoice_p
        )

    def snapshot(self) -> str:
        return _SNAPSHOT

    def run_trial(
        self, snapshot: str, assignment: dict[str, bool], seed: int
    ) -> RawRun:
        rng = random.Random(seed)
        invoice = fixture.generate_invoice(rng, self._large_invoice_p)
        page = fixture.render_page(invoice, assignment)
        artifact = fixture.run_agent(page, assignment, rng)
        duration_ms = 900 + rng.randint(0, 700)
        if assignment.get("network_latency", True):
            duration_ms += rng.randint(300, 1400)
        return RawRun(
            artifact=artifact,
            transcript=tuple(artifact["steps"]),
            duration_ms=duration_ms,
        )

    def close(self) -> None:
        return None


def _plain_artifact(
    invoice: dict[str, Any], fail: bool, rng: random.Random
) -> dict[str, Any]:
    """Build a fixture-shaped artifact that fails by botching the total."""
    total = invoice["expected_total"]
    entered = total + rng.randint(120, 9_000) if fail else total
    steps = [
        f"open invoice from {invoice['vendor']}",
        f"type PO {invoice['po_number']}",
        f"enter total {entered} cents",
        "submit form",
    ]
    return {
        "po_entered": invoice["po_number"],
        "total_entered": entered,
        "expected_po": invoice["po_number"],
        "expected_total": total,
        "timed_out": False,
        "steps": steps,
    }


class NoEffectWorld:
    """Fails about 30% of the time no matter what is neutralized.

    The assignment is never read. A given seed produces the same outcome
    on every branch, so any cause reported against this world is a false
    positive by construction. The type-I calibration suite leans on that.
    """

    FAILURE_P = 0.30

    def snapshot(self) -> str:
        return _SNAPSHOT

    def run_trial(
        self, snapshot: str, assignment: dict[str, bool], seed: int
    ) -> RawRun:
        rng = random.Random(seed)
        invoice = fixture.generate_invoice(rng)
        fail = rng.random() < self.FAILURE_P
        artifact = _plain_artifact(invoice, fail, rng)
        return RawRun(
            artifact=artifact,
            transcript=tuple(artifact["steps"]),
            duration_ms=900 + rng.randint(0, 700),
        )

    def close(self) -> None:
        return None


class ConjunctionWorld:
    """Fails hard until cookie_banner and network_latency are both gone.

    Failure runs near 60% while either factor of the pair stays active
    and drops to about 3% once a branch neutralizes both together. No
    single-factor branch can rescue the run, which is exactly the shape
    the pairwise escalation in search.py exists to catch. The verdict
    that fits this world names the pair, not either half of it.
    """

    PAIR = ("cookie_banner", "network_latency")
    FAIL_ACTIVE_P = 0.60
    FAIL_CLEAR_P = 0.03

    def snapshot(self) -> str:
        return _SNAPSHOT

    def run_trial(
        self, snapshot: str, assignment: dict[str, bool], seed: int
    ) -> RawRun:
        rng = random.Random(seed)
        invoice = fixture.generate_invoice(rng)
        pair_cleared = not any(
            assignment.get(factor_id, True) for factor_id in self.PAIR
        )
        p_fail = self.FAIL_CLEAR_P if pair_cleared else self.FAIL_ACTIVE_P
        fail = rng.random() < p_fail
        artifact = _plain_artifact(invoice, fail, rng)
        return RawRun(
            artifact=artifact,
            transcript=tuple(artifact["steps"]),
            duration_ms=900 + rng.randint(0, 700),
        )

    def close(self) -> None:
        return None
