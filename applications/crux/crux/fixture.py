"""The invoice-entry scenario Crux investigates in the demo.

A simulated browser agent opens a vendor invoice, types the PO number,
adds up the line items, and submits the total. The bug is real code, not
a rigged coin flip: the extraction routine walks only the first column
of the line-item table. Short invoices render in one column and survive.
Long ones split into two when the layout factor is active, and each of
those runs enters a total that is short by the whole second column.

Four other factors add noise or nothing. Sampling temperature can typo
the PO. The consent banner can swallow a click. Latency can time out the
page load. Context trimming does nothing at all and exists to tempt the
engine into a false accusation.

All randomness flows through the rng argument, so a trial is a pure
function of its seed and its factor assignment.
"""

from __future__ import annotations

import math
import random
from typing import Any

from .models import Factor

FACTORS: tuple[Factor, ...] = (
    Factor(
        id="two_column_layout",
        description="long line-item tables render in two columns",
    ),
    Factor(
        id="cookie_banner",
        description="consent banner overlays the page until dismissed",
    ),
    Factor(
        id="model_temperature",
        description="agent samples tokens at nonzero temperature",
    ),
    Factor(
        id="network_latency",
        description="extra latency injected on page loads",
    ),
    Factor(
        id="context_trim",
        description="older conversation context trimmed before each step",
    ),
)

# Event rates. Each event is drawn independently from the trial rng.
# Tuned so the default demo decides on seed 7 and the power suite clears
# its 0.9 bar: the large-invoice rate went up a little and the noise
# rates came down, while the baseline failure rate stays inside the
# contract's 0.26 to 0.38 band.
LARGE_INVOICE_P = 0.36
TYPO_P = 0.005
MISCLICK_P = 0.005
TIMEOUT_P = 0.003

_VENDORS = (
    "Acme Supply Co",
    "Northwind Traders",
    "Bellwether Freight",
    "Cascade Instruments",
    "Harbor & Sons",
)

_SERVICES = (
    "hosting",
    "support hours",
    "license seats",
    "freight",
    "assembly",
    "calibration",
    "site survey",
    "spare parts",
)


def generate_invoice(
    rng: random.Random, large_invoice_p: float = LARGE_INVOICE_P
) -> dict[str, Any]:
    """Draw one invoice. Roughly a third have more than ten line items.

    large_invoice_p sets how often an invoice is long enough to trigger
    the two-column split. The default keeps the demo calibration; the
    benchmark lowers it to study a weaker causal signal. Changing the
    value does not change how much randomness a call consumes, so trials
    stay comparable across settings for a given seed.
    """
    if rng.random() < large_invoice_p:
        count = rng.randint(11, 18)
    else:
        count = rng.randint(3, 10)
    line_items = [
        {
            "description": f"{rng.choice(_SERVICES)} #{index + 1:02d}",
            "amount_cents": rng.randint(250, 98_000),
        }
        for index in range(count)
    ]
    po_number = "PO-" + "".join(str(rng.randint(0, 9)) for _ in range(6))
    return {
        "vendor": rng.choice(_VENDORS),
        "po_number": po_number,
        "line_items": line_items,
        "expected_total": sum(item["amount_cents"] for item in line_items),
    }


def render_page(
    invoice: dict[str, Any], assignment: dict[str, bool]
) -> dict[str, Any]:
    """Lay the invoice out the way the agent will see it.

    The two-column split applies only when that factor is active and the
    invoice has more than ten line items. Small invoices always render as
    one column, which is why the bug hides so well in spot checks.
    """
    items = invoice["line_items"]
    if assignment.get("two_column_layout", True) and len(items) > 10:
        split = math.ceil(len(items) / 2)
        columns = [items[:split], items[split:]]
    else:
        columns = [items]
    return {
        "vendor": invoice["vendor"],
        "po_number": invoice["po_number"],
        "columns": columns,
        "banner": assignment.get("cookie_banner", True),
    }


def _extract_total(page: dict[str, Any]) -> int:
    """Sum the line items the way the agent actually does it.

    This is the defect under investigation. The loop covers the first
    column and never asks whether the table rendered a second one.
    """
    return sum(item["amount_cents"] for item in page["columns"][0])


def _typo(text: str, rng: random.Random) -> str:
    """Replace one digit of the text with a different digit."""
    positions = [i for i, ch in enumerate(text) if ch.isdigit()]
    pos = rng.choice(positions)
    replacement = rng.choice([d for d in "0123456789" if d != text[pos]])
    return text[:pos] + replacement + text[pos + 1 :]


def run_agent(
    page: dict[str, Any], assignment: dict[str, bool], rng: random.Random
) -> dict[str, Any]:
    """Run the simulated entry agent against one rendered page."""
    expected_po = page["po_number"]
    expected_total = sum(
        item["amount_cents"] for column in page["columns"] for item in column
    )
    steps = [f"open invoice from {page['vendor']}"]

    if assignment.get("network_latency", True) and rng.random() < TIMEOUT_P:
        steps.append("page load timed out, giving up")
        return {
            "po_entered": "",
            "total_entered": None,
            "expected_po": expected_po,
            "expected_total": expected_total,
            "timed_out": True,
            "steps": steps,
        }

    po_field_blocked = False
    if page["banner"]:
        if rng.random() < MISCLICK_P:
            po_field_blocked = True
            steps.append("click on PO field hit the consent banner")
        else:
            steps.append("dismiss consent banner")

    if po_field_blocked:
        po_entered = ""
    else:
        po_entered = expected_po
        if assignment.get("model_temperature", True) and rng.random() < TYPO_P:
            po_entered = _typo(po_entered, rng)
        steps.append(f"type PO {po_entered}")

    if assignment.get("context_trim", True):
        steps.append("trim older context")

    total_entered = _extract_total(page)
    steps.append(f"enter total {total_entered} cents")
    steps.append("submit form")
    return {
        "po_entered": po_entered,
        "total_entered": total_entered,
        "expected_po": expected_po,
        "expected_total": expected_total,
        "timed_out": False,
        "steps": steps,
    }


def oracle(artifact: dict[str, Any]) -> tuple[bool, str]:
    """Score one artifact. Pass means the run finished and both fields match."""
    if artifact["timed_out"]:
        return False, "timed out before the form was submitted"
    if artifact["po_entered"] != artifact["expected_po"]:
        return False, (
            f"po mismatch: entered {artifact['po_entered']!r}, "
            f"expected {artifact['expected_po']!r}"
        )
    if artifact["total_entered"] != artifact["expected_total"]:
        return False, (
            f"total mismatch: entered {artifact['total_entered']}, "
            f"expected {artifact['expected_total']}"
        )
    return True, "po and total both correct"
