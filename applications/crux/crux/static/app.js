/* Crux dashboard. Plain browser JS, no dependencies.
   Reads /data/investigation.json and renders it. */

"use strict";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function fmtP(p) {
  if (p === null || p === undefined) return "";
  if (p === 0) return "0";
  if (p < 0.0001) return p.toExponential(2);
  return p.toPrecision(3).replace(/\.?0+$/, "");
}

function fmtRate(rate) {
  return rate.toFixed(3);
}

/* Wilson score interval, matching stats.wilson_ci on the Python side. */
function wilson(successes, n, z) {
  z = z || 1.96;
  if (n === 0) return [0, 1];
  const phat = successes / n;
  const z2 = z * z;
  const denom = 1 + z2 / n;
  const centre = phat + z2 / (2 * n);
  const spread = z * Math.sqrt((phat * (1 - phat) + z2 / (4 * n)) / n);
  return [
    Math.max(0, (centre - spread) / denom),
    Math.min(1, (centre + spread) / denom),
  ];
}

function causeBranchId(cause) {
  if (!cause || cause.length === 0) return null;
  return cause
    .slice()
    .sort()
    .map((factor) => "no-" + factor)
    .join("+");
}

function branchStatus(branch, inv) {
  if (branch.branch_id === "baseline") return "baseline";
  const verdict = inv.verdict;
  if (
    verdict &&
    verdict.cause &&
    verdict.cause.slice().sort().join("+") ===
      branch.neutralized.slice().sort().join("+")
  ) {
    return "cause";
  }
  if (branch.dropped_for_futility) return "dropped for futility";
  if (branch.confirmation_failed) return "confirmation failed";
  return "live";
}

function renderVerdict(inv) {
  const banner = document.getElementById("verdict");
  banner.textContent = "";
  banner.classList.remove("pending");
  const verdict = inv.verdict;

  if (!verdict) {
    banner.classList.add("undecided");
    banner.appendChild(el("h2", "banner-title", "No verdict recorded"));
    banner.appendChild(
      el(
        "p",
        null,
        "The investigation stopped before it could decide or exhaust its budget."
      )
    );
    return;
  }

  if (verdict.cause) {
    banner.classList.add("decided");
    banner.appendChild(
      el("h2", "banner-title", "Cause confirmed: " + verdict.cause.join(" + "))
    );
  } else {
    banner.classList.add("undecided");
    banner.appendChild(el("h2", "banner-title", "Undecided"));
  }
  banner.appendChild(el("p", null, verdict.summary));

  const facts = el("p", "muted");
  const bits = [
    "alpha " + verdict.alpha,
    verdict.trials_total + " trials",
    verdict.rounds + " rounds",
  ];
  if (verdict.confirmation_p !== null && verdict.confirmation_p !== undefined) {
    bits.push("confirmation p " + fmtP(verdict.confirmation_p));
  }
  facts.textContent = bits.join(" | ");
  banner.appendChild(facts);
}

function renderConfirmation(inv) {
  const panel = document.getElementById("confirmation");
  const body = document.getElementById("confirmation-body");
  body.textContent = "";
  panel.classList.remove("hidden");
  const verdict = inv.verdict;

  if (!verdict) {
    body.appendChild(
      el("p", "muted", "No verdict, so no confirmation batch was run.")
    );
    return;
  }

  if (verdict.cause) {
    const branchId = causeBranchId(verdict.cause);
    const branch = branchId ? inv.branches[branchId] : null;
    body.appendChild(
      el(
        "p",
        null,
        "A fresh batch of trials was run on the winning branch and the " +
          "baseline, then tested once at the full alpha of " +
          verdict.alpha +
          "."
      )
    );
    const grid = el("div", "confirm-grid");
    grid.appendChild(confirmCell("Confirmation p", fmtP(verdict.confirmation_p)));
    grid.appendChild(confirmCell("Baseline rate", fmtRate(verdict.baseline_rate)));
    if (verdict.cause_rate !== null && verdict.cause_rate !== undefined) {
      grid.appendChild(confirmCell("Cause branch rate", fmtRate(verdict.cause_rate)));
    }
    if (branch) {
      grid.appendChild(
        confirmCell(
          "Cause branch tally",
          branch.successes + " / " + branch.trials + " passed"
        )
      );
    }
    body.appendChild(grid);
  } else {
    body.appendChild(
      el(
        "p",
        null,
        "No branch passed a confirmation batch. The verdict names no cause."
      )
    );
    const failed = Object.values(inv.branches).filter(
      (b) => b.confirmation_failed
    );
    if (failed.length > 0) {
      body.appendChild(
        el(
          "p",
          "muted",
          "Branches that reached confirmation but failed it: " +
            failed.map((b) => b.branch_id).join(", ")
        )
      );
    }
  }
}

function confirmCell(label, value) {
  const cell = el("div", "confirm-cell");
  cell.appendChild(el("div", "confirm-label", label));
  cell.appendChild(el("div", "confirm-value", value));
  return cell;
}

function orderedBranches(inv) {
  const all = Object.values(inv.branches);
  const baseline = all.filter((b) => b.branch_id === "baseline");
  const active = [];
  const inactive = [];
  for (const b of all) {
    if (b.branch_id === "baseline") continue;
    if (b.dropped_for_futility || b.confirmation_failed) inactive.push(b);
    else active.push(b);
  }
  const byInterest = (a, b) => {
    const pa = a.p_value === null || a.p_value === undefined ? 2 : a.p_value;
    const pb = b.p_value === null || b.p_value === undefined ? 2 : b.p_value;
    if (pa !== pb) return pa - pb;
    return a.branch_id < b.branch_id ? -1 : 1;
  };
  active.sort(byInterest);
  inactive.sort(byInterest);
  return baseline.concat(active, inactive);
}

function renderBranches(inv) {
  const host = document.getElementById("branches");
  host.textContent = "";
  const baseline = inv.branches["baseline"];
  const baseRate = baseline ? baseline.rate : null;

  for (const branch of orderedBranches(inv)) {
    const status = branchStatus(branch, inv);
    const row = el("div", "branch-row");
    if (status === "dropped for futility" || status === "confirmation failed") {
      row.classList.add("greyed");
    }
    if (status === "cause") row.classList.add("cause");
    if (status === "baseline") row.classList.add("baseline");

    const head = el("div", "branch-head");
    head.appendChild(el("span", "branch-id", branch.branch_id));
    head.appendChild(el("span", "branch-status", status));
    row.appendChild(head);

    const [lo, hi] = wilson(branch.successes, branch.trials);
    const track = el("div", "track");
    const bar = el("div", "bar");
    bar.style.width = (branch.rate * 100).toFixed(2) + "%";
    track.appendChild(bar);
    if (branch.trials > 0) {
      const ci = el("div", "ci");
      ci.style.left = (lo * 100).toFixed(2) + "%";
      ci.style.width = (Math.max(0, hi - lo) * 100).toFixed(2) + "%";
      track.appendChild(ci);
    }
    if (baseRate !== null && branch.branch_id !== "baseline") {
      const marker = el("div", "baseline-marker");
      marker.style.left = (baseRate * 100).toFixed(2) + "%";
      marker.title = "baseline rate";
      track.appendChild(marker);
    }
    row.appendChild(track);

    const metaBits = [
      "rate " + fmtRate(branch.rate) +
        " (" + branch.successes + "/" + branch.trials + ")",
      "CI [" + fmtRate(lo) + ", " + fmtRate(hi) + "]",
    ];
    if (branch.p_value !== null && branch.p_value !== undefined) {
      metaBits.push("p " + fmtP(branch.p_value));
    }
    if (branch.neutralized.length > 0) {
      metaBits.push("neutralized: " + branch.neutralized.join(", "));
    }
    row.appendChild(el("div", "branch-meta muted", metaBits.join("  |  ")));
    host.appendChild(row);
  }
}

function renderTimeline(inv) {
  const host = document.getElementById("timeline");
  host.textContent = "";
  if (!inv.round_log || inv.round_log.length === 0) {
    host.appendChild(el("li", "muted", "No rounds logged."));
    return;
  }
  for (const entry of inv.round_log) {
    const item = el("li", "round");
    const head = el("div", "round-head");
    head.appendChild(el("span", "round-num", "Round " + (entry.round ?? "?")));
    if (entry.alpha_spent !== undefined) {
      head.appendChild(
        el("span", "muted", "alpha spent " + fmtP(entry.alpha_spent))
      );
    }
    item.appendChild(head);

    const allocs = entry.allocations || {};
    const allocText = Object.entries(allocs)
      .map(([k, v]) => k + " " + v)
      .join(", ");
    if (allocText) {
      item.appendChild(el("div", "muted", "allocated: " + allocText));
    }

    const ps = entry.p_values || {};
    const keys = Object.keys(ps);
    if (keys.length > 0) {
      const chips = el("div", "chips");
      keys
        .sort((a, b) => ps[a] - ps[b])
        .forEach((k) => {
          chips.appendChild(el("span", "chip", k + " p=" + fmtP(ps[k])));
        });
      item.appendChild(chips);
    }

    for (const [key, value] of Object.entries(entry)) {
      if (["round", "alpha_spent", "allocations", "p_values"].includes(key)) {
        continue;
      }
      item.appendChild(el("div", "muted", key + ": " + JSON.stringify(value)));
    }
    host.appendChild(item);
  }
}

function renderTrials(inv) {
  const summary = document.getElementById("trials-summary");
  const body = document.querySelector("#trials-table tbody");
  body.textContent = "";
  const trials = inv.trials || [];
  summary.textContent = "Show all " + trials.length + " trials";
  trials.forEach((trial, index) => {
    const row = el("tr", trial.passed ? "pass" : "fail");
    row.appendChild(el("td", null, String(index + 1)));
    row.appendChild(el("td", null, trial.branch_id));
    row.appendChild(el("td", "muted", String(trial.seed)));
    row.appendChild(el("td", null, trial.passed ? "pass" : "fail"));
    row.appendChild(el("td", null, trial.detail));
    row.appendChild(el("td", "muted", String(trial.duration_ms)));
    body.appendChild(row);
  });
}

function render(inv) {
  const subtitle = document.getElementById("subtitle");
  subtitle.textContent =
    inv.investigation_id +
    "  |  scenario: " + (inv.scenario || "unnamed") +
    "  |  seed " + inv.config.seed;
  renderVerdict(inv);
  renderConfirmation(inv);
  renderBranches(inv);
  renderTimeline(inv);
  renderTrials(inv);
}

function showLoadError(banner, message) {
  banner.classList.remove("pending");
  banner.classList.add("undecided");
  banner.textContent = message;
}

async function load() {
  const banner = document.getElementById("verdict");
  let inv;
  try {
    const res = await fetch("/data/investigation.json");
    if (!res.ok) throw new Error("HTTP " + res.status);
    inv = await res.json();
  } catch (err) {
    showLoadError(
      banner,
      "Could not load /data/investigation.json (" + err.message + "). " +
        "Start the server with: crux serve --directory <bundle-dir>"
    );
    return;
  }
  try {
    render(inv);
  } catch (err) {
    showLoadError(
      banner,
      "investigation.json loaded but could not be rendered (" + err.message +
        "). The file is reachable; its contents do not match what this " +
        "viewer expects."
    );
  }
}

load();
