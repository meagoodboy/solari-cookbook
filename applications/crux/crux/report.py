"""Write an investigation bundle to disk.

A bundle is one directory holding three views of the same run:
investigation.json for machines, report.md for people, branches.csv
for spreadsheets. The dashboard in serve.py reads the JSON file.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .models import BranchState, Investigation, Verdict
from .stats import wilson_ci


def write_bundle(
    inv: Investigation, out_dir: Path, world_spec: dict | None = None
) -> Path:
    """Write investigation.json, report.md and branches.csv into out_dir.

    When world_spec is given (a World's to_spec() output), it lands as
    world.json beside the bundle so `crux verify` can rebuild the world
    and replay the investigation. Creates the directory if needed and
    returns it.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if world_spec is not None:
        (out_dir / "world.json").write_text(
            json.dumps(world_spec, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    json_path = out_dir / "investigation.json"
    json_path.write_text(
        json.dumps(inv.to_dict(), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )

    (out_dir / "report.md").write_text(_render_markdown(inv, out_dir), encoding="utf-8")
    _write_csv(inv, out_dir / "branches.csv")
    return out_dir


def _ordered_branches(inv: Investigation) -> list[BranchState]:
    """Baseline first, everything else by id."""
    rest = sorted(
        (s for k, s in inv.branches.items() if k != "baseline"),
        key=lambda s: s.branch_id,
    )
    base = inv.branches.get("baseline")
    return ([base] if base else []) + rest


def _branch_status(state: BranchState, verdict: Verdict | None) -> str:
    if state.branch_id == "baseline":
        return "baseline"
    if (
        verdict is not None
        and verdict.cause is not None
        and tuple(verdict.cause) == tuple(state.neutralized)
    ):
        return "cause"
    if state.dropped_for_futility:
        return "dropped for futility"
    if state.confirmation_failed:
        return "confirmation failed"
    return "live"


def _fmt_p(p: float | None) -> str:
    return f"{p:.4g}" if p is not None else ""


def _fmt_ci(succ: int, n: int) -> str:
    lo, hi = wilson_ci(succ, n)
    return f"[{lo:.3f}, {hi:.3f}]"


def _fmt_alloc(mapping: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in mapping.items()) or "none"


def _render_markdown(inv: Investigation, out_dir: Path) -> str:
    lines: list[str] = []
    lines.append(f"# Crux report: {inv.investigation_id}")
    lines.append("")
    scenario = inv.scenario or "unnamed"
    lines.append(f"Scenario {scenario}, seed {inv.config.seed}, alpha {inv.config.alpha}.")
    lines.append("")

    lines.append("## Verdict")
    lines.append("")
    v = inv.verdict
    if v is None:
        lines.append(
            "No verdict was recorded. The investigation stopped before it "
            "could decide or exhaust its budget."
        )
    else:
        lines.append(v.summary)
        lines.append("")
        if v.cause is not None:
            lines.append(f"Cause: {', '.join(v.cause)}")
            lines.append(f"Confirmation p: {_fmt_p(v.confirmation_p)}")
            if v.cause_rate is not None:
                lines.append(
                    f"Success rate moved from {v.baseline_rate:.3f} at baseline "
                    f"to {v.cause_rate:.3f} with the cause neutralized."
                )
        else:
            lines.append("Cause: none met the significance bar.")
        lines.append(
            f"Spent {v.trials_total} trials over {v.rounds} rounds, "
            f"within a budget of {inv.config.max_trials} trials and "
            f"{inv.config.max_rounds} rounds."
        )
    lines.append("")

    lines.append("## Branches")
    lines.append("")
    lines.append("| branch | neutralized | trials | successes | rate | Wilson 95% CI | p vs baseline | status |")
    lines.append("| --- | --- | ---: | ---: | ---: | --- | ---: | --- |")
    for state in _ordered_branches(inv):
        neutralized = ", ".join(state.neutralized) or "(none)"
        lines.append(
            f"| {state.branch_id} | {neutralized} | {state.trials} "
            f"| {state.successes} | {state.rate:.3f} "
            f"| {_fmt_ci(state.successes, state.trials)} "
            f"| {_fmt_p(state.p_value)} | {_branch_status(state, v)} |"
        )
    lines.append("")
    lines.append(
        "The p column is the value from each branch's last exploratory look. "
        "Trial and success counts also include any confirmation batch run "
        "afterwards, so recomputing Fisher from a row's own counts will not "
        "reproduce its p. The round log below carries the per-look counts "
        "and the confirmation batch tallies."
    )
    lines.append("")

    lines.append("## Round log")
    lines.append("")
    if not inv.round_log:
        lines.append("No rounds were logged.")
    for entry in inv.round_log:
        entry = dict(entry)
        number = entry.pop("round", "?")
        alpha_spent = entry.pop("alpha_spent", None)
        allocations = entry.pop("allocations", {})
        p_values = entry.pop("p_values", {})
        lines.append(f"### Round {number}")
        lines.append("")
        if alpha_spent is not None:
            lines.append(f"Alpha spent this look: {_fmt_p(alpha_spent)}.")
        lines.append(f"Allocations: {_fmt_alloc(allocations)}.")
        if p_values:
            shown = ", ".join(f"{k}={_fmt_p(p)}" for k, p in p_values.items())
            lines.append(f"P values: {shown}.")
        for key, value in entry.items():
            lines.append(f"{key}: {json.dumps(value)}")
        lines.append("")

    lines.append("## How to replay")
    lines.append("")
    lines.append(
        f"Run `crux verify {out_dir}` to rerun the investigation from its "
        "saved seed and check that the same cause comes back. "
        f"Run `crux serve --directory {out_dir}` to open the dashboard."
    )
    lines.append("")
    return "\n".join(lines)


def _write_csv(inv: Investigation, path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "branch_id",
                "neutralized",
                "trials",
                "successes",
                "rate",
                "wilson_low",
                "wilson_high",
                "p_value",
                "status",
            ]
        )
        for state in _ordered_branches(inv):
            lo, hi = wilson_ci(state.successes, state.trials)
            writer.writerow(
                [
                    state.branch_id,
                    "+".join(state.neutralized),
                    state.trials,
                    state.successes,
                    f"{state.rate:.6f}",
                    f"{lo:.6f}",
                    f"{hi:.6f}",
                    "" if state.p_value is None else repr(state.p_value),
                    _branch_status(state, inv.verdict),
                ]
            )
