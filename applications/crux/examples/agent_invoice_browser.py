"""Investigate a real language-model agent on a real Solari cloud browser.

This is the case the rest of the repository builds toward. The agent is
an actual LLM (a small local model served by ollama), the page it reads
is rendered by a real Solari cloud browser, and the text it consumes is
the browser's own linearization of the DOM. Nothing about the failure
is scripted: whatever confuses the model comes from the page, the
prompt, the sampling, and the layout, and Crux has to find which.

The task: read an invoice page and return the PO number and the amount
due as JSON. Five suspects, all real knobs:

- model_temperature: sampled decoding at 1.0 with a per-trial seed
  against greedy decoding at 0. Ollama honors both, so even the
  sampled runs replay exactly on the same model build.
- two_column_layout: the invoice renders in two CSS columns, which
  changes the reading order the browser hands the model.
- context_trim: the agent sees only the first 500 characters of the page text,
  the way a context limit would cut it.
- terse_prompt: a one-line instruction against a careful one that says
  exactly which figure to report.
- distractor_boilerplate: footer marketing with other dollar amounts.

Requirements: SOLARI_API_KEY in the environment, and ollama running
locally with the model pulled (default qwen2.5:1.5b-instruct). The
model is local and free; the browser session is the only paid piece,
and one session is reused across every trial to keep the cost small.

Run:
  python examples/agent_invoice_browser.py --yes
  python examples/agent_invoice_browser.py --calibrate   (probe rates only)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from random import Random

from crux.models import Factor, InvestigationConfig, RawRun
from crux.report import write_bundle
from crux.search import investigate
from crux.stats import trial_seed

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "qwen2.5:1.5b-instruct"
TRIM_CHARS = 500

FACTORS = (
    Factor("model_temperature", "sampled decoding at temperature 1.0"),
    Factor("two_column_layout", "invoice rendered in two CSS columns"),
    Factor("context_trim", "page text cut to the first 500 characters"),
    Factor("terse_prompt", "one-line instruction without field definitions"),
    Factor("distractor_boilerplate", "footer marketing with other dollar amounts"),
)

VENDORS = ("Alpine Office Supply", "Meridian Freight", "Cobalt Labs", "Harbor Print Co")
ITEMS = (
    "Copy paper, letter", "Toner cartridge", "Shipping pallet", "Packing tape",
    "Label rolls", "Binder clips", "USB cables", "Desk lamp", "Whiteboard markers",
    "Envelope box", "Stapler", "Monitor stand", "Cable ties", "Notebook pack",
)


def generate_invoice(rng: Random) -> dict:
    po = f"PO-{rng.randrange(10000, 99999)}"
    count = rng.randrange(10, 25)
    line_items = []
    for _ in range(count):
        name = rng.choice(ITEMS)
        qty = rng.randrange(1, 9)
        cents = rng.randrange(199, 24999)
        line_items.append((name, qty, qty * cents))
    amount_due = sum(total for _, _, total in line_items)
    previous_balance = rng.randrange(1000, 99999)
    return {
        "vendor": rng.choice(VENDORS),
        "po": po,
        "line_items": line_items,
        "amount_due": amount_due,
        "previous_balance": previous_balance,
    }


def _dollars(cents: int) -> str:
    return f"${cents // 100:,}.{cents % 100:02d}"


def render_html(invoice: dict, assignment: dict[str, bool]) -> str:
    rows = "".join(
        f"<tr><td>{name}</td><td>{qty}</td><td>{_dollars(total)}</td></tr>"
        for name, qty, total in invoice["line_items"]
    )
    subtotal = invoice["amount_due"]
    shipping = invoice["previous_balance"] % 5000 + 899
    tax = round(subtotal * 0.08)
    due = subtotal + shipping + tax
    invoice["amount_due"] = due
    exposure = due + invoice["previous_balance"]
    summary = (
        "<div class='summary'>"
        f"<p>Subtotal: {_dollars(subtotal)}</p>"
        f"<p>Shipping: {_dollars(shipping)}</p>"
        f"<p>Tax (8%): {_dollars(tax)}</p>"
        f"<p>Previous balance: {_dollars(invoice['previous_balance'])}</p>"
        f"<p>Amount due: {_dollars(due)}</p>"
        f"<p>Total account exposure: {_dollars(exposure)}</p>"
        "<p>Payment terms: net 30.</p>"
        "</div>"
    )
    footer = ""
    if assignment.get("distractor_boilerplate", True):
        footer = (
            "<footer><p>Save $25.00 on your next order over $500.00.</p>"
            "<p>Refer a partner and earn a $50.00 account credit.</p>"
            "<p>Autopay enrollment waives the $9.99 processing fee.</p>"
            "<p>Late payments accrue a $35.00 monthly charge.</p>"
            "<p>Questions? Our billing line is open weekdays.</p></footer>"
        )
    column_css = (
        "column-count: 2; column-gap: 24px;"
        if assignment.get("two_column_layout", True)
        else ""
    )
    return (
        "<html><head><style>"
        f"main {{ {column_css} font-family: sans-serif; }}"
        "table { border-collapse: collapse; } td { padding: 2px 8px; }"
        "</style></head><body><main>"
        f"<h1>{invoice['vendor']}</h1>"
        f"<p>Purchase order: {invoice['po']}</p>"
        f"<table>{rows}</table>"
        f"{summary}"
        "</main>"
        f"{footer}"
        "</body></html>"
    )


def build_prompt(page_text: str, assignment: dict[str, bool]) -> str:
    if assignment.get("context_trim", True):
        page_text = page_text[:TRIM_CHARS]
    if assignment.get("terse_prompt", True):
        instruction = (
            "Extract the PO number and amount due from this invoice. "
            'Reply with JSON only: {"po": "...", "amount_due": "..."}'
        )
    else:
        instruction = (
            "Read the invoice text below. Report the purchase order number "
            "(the value after 'Purchase order:') and the amount due (the "
            "figure labeled 'Amount due', not the previous balance and not "
            "any promotional amount). Reply with JSON only, exactly "
            '{"po": "...", "amount_due": "..."} and nothing else.'
        )
    return f"{instruction}\n\nInvoice text:\n{page_text}"


def call_model(model: str, prompt: str, assignment: dict[str, bool], seed: int) -> str:
    if assignment.get("model_temperature", True):
        options = {"temperature": 1.0, "seed": seed % 2**31}
    else:
        options = {"temperature": 0.0, "seed": 0}
    options["num_predict"] = 160
    body = json.dumps(
        {"model": model, "prompt": prompt, "stream": False, "options": options}
    ).encode()
    request = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read())
    return payload.get("response", "")


_AMOUNT_JUNK = re.compile(r"[,$\s]")


def _normalize_amount(value) -> int | None:
    text = _AMOUNT_JUNK.sub("", str(value))
    if not text:
        return None
    try:
        return round(float(text) * 100)
    except ValueError:
        return None


def parse_reply(reply: str) -> tuple[str | None, int | None]:
    match = None
    for candidate in re.findall(r"\{[^{}]*\}", reply, flags=re.DOTALL):
        try:
            match = json.loads(candidate)
        except json.JSONDecodeError:
            continue
    if not isinstance(match, dict):
        return None, None
    po = match.get("po")
    return (str(po).strip() if po else None), _normalize_amount(
        match.get("amount_due")
    )


def oracle(artifact: dict) -> tuple[bool, str]:
    if artifact.get("error"):
        return False, f"trial error: {artifact['error']}"
    if artifact["po_entered"] != artifact["expected_po"]:
        return False, f"po mismatch: {artifact['po_entered']!r}"
    if artifact["amount_entered"] != artifact["expected_amount"]:
        return False, f"amount mismatch: {artifact['amount_entered']!r}"
    return True, "po and amount correct"


class LLMBrowserWorld:
    """World protocol over one Solari browser session and a local model.

    The frozen world is the invoice fixture definition; each trial gets
    a fresh page in a shared cloud browser session (cheaper than a
    session per trial, and pages do not share state that matters here).
    A dead session is relaunched once per trial.
    """

    def __init__(self, api_key: str, model: str, progress=None) -> None:
        self._api_key = api_key
        self._model = model
        self._progress = progress or (lambda line: None)
        self._loop = asyncio.new_event_loop()
        self._solari = None
        self._browser = None
        self.trials_run = 0

    def snapshot(self) -> str:
        return "invoice-agent-fixture-v1"

    def run_trial(
        self, snapshot: str, assignment: dict[str, bool], seed: int
    ) -> RawRun:
        started = time.monotonic()
        rng = Random(seed)
        invoice = generate_invoice(rng)
        html = render_html(invoice, assignment)
        last_error = None
        page_text = None
        for attempt in range(2):
            try:
                page_text = self._loop.run_until_complete(self._page_text(html))
                break
            except Exception as exc:
                last_error = exc
                self._loop.run_until_complete(self._teardown_browser())
        artifact: dict = {
            "expected_po": invoice["po"],
            "expected_amount": invoice["amount_due"],
            "seed": seed,
        }
        if page_text is None:
            artifact.update(
                error=f"browser failed twice: {last_error}",
                po_entered=None, amount_entered=None, reply_tail="",
            )
        else:
            prompt = build_prompt(page_text, assignment)
            try:
                reply = call_model(self._model, prompt, assignment, seed)
                po, amount = parse_reply(reply)
                artifact.update(
                    error=None, po_entered=po, amount_entered=amount,
                    reply_tail=reply[-300:], page_chars=len(page_text),
                )
            except Exception as exc:
                artifact.update(
                    error=f"model call failed: {exc}",
                    po_entered=None, amount_entered=None, reply_tail="",
                )
        self.trials_run += 1
        duration_ms = int((time.monotonic() - started) * 1000)
        transcript = (
            f"invoice {invoice['po']} with {len(invoice['line_items'])} items",
            f"assignment {sorted(k for k, v in assignment.items() if not v)}"
            " neutralized",
            f"outcome {artifact['po_entered']!r} / {artifact['amount_entered']!r}",
        )
        return RawRun(artifact=artifact, transcript=transcript, duration_ms=duration_ms)

    async def _page_text(self, html: str) -> str:
        if self._browser is None:
            from solari_browser import Solari

            self._solari = Solari(api_key=self._api_key)
            self._browser = await self._solari.launch()
            self._progress(f"browser session {self._browser.id} launched")
        page = await self._browser.new_page()
        try:
            await page.set_content(html)
            return await page.inner_text("body")
        finally:
            await page.close()

    async def _teardown_browser(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
        self._browser = None
        self._solari = None

    def close(self) -> None:
        try:
            self._loop.run_until_complete(self._teardown_browser())
        finally:
            self._loop.close()


def check_ollama(model: str) -> str | None:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:11434/api/tags", timeout=5
        ) as response:
            tags = json.loads(response.read())
    except Exception as exc:
        return f"ollama is not reachable on 127.0.0.1:11434 ({exc})"
    names = [entry.get("name", "") for entry in tags.get("models", [])]
    if not any(name.startswith(model) for name in names):
        return f"model {model} is not pulled (have: {', '.join(names) or 'none'})"
    return None


def run_calibration(world: LLMBrowserWorld, master_seed: int, per_arm: int) -> None:
    arms: dict[str, dict[str, bool]] = {
        "baseline": {f.id: True for f in FACTORS}
    }
    for factor in FACTORS:
        assignment = {f.id: True for f in FACTORS}
        assignment[factor.id] = False
        arms[f"no-{factor.id}"] = assignment
    for arm, assignment in arms.items():
        passes = 0
        for index in range(per_arm):
            seed = trial_seed(master_seed, f"calibrate:{arm}", index)
            raw = world.run_trial(world.snapshot(), assignment, seed)
            passed, _ = oracle(raw.artifact)
            passes += int(passed)
        print(f"  {arm}: {passes}/{per_arm} passed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Investigate a real LLM agent on a Solari cloud browser"
    )
    parser.add_argument("--yes", action="store_true", help="accept browser charges")
    parser.add_argument("--calibrate", action="store_true", help="probe rates only")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", default="proof/agent")
    parser.add_argument("--per-arm", type=int, default=6, help="calibration trials per arm")
    args = parser.parse_args(argv)

    api_key = os.environ.get("SOLARI_API_KEY", "")
    if not api_key:
        print("SOLARI_API_KEY is not set; export it and rerun.")
        return 2
    problem = check_ollama(args.model)
    if problem:
        print(problem)
        return 2

    config = InvestigationConfig(
        max_trials=240, max_rounds=6, round_trials_per_branch=8,
        confirm_trials=20, futility_min_trials=16, seed=args.seed,
    )
    cap = args.per_arm * 6 if args.calibrate else config.max_trials
    print(f"One Solari browser session, reused across at most {cap} trials.")
    print("The model runs locally through ollama and costs nothing.")
    if not args.yes and not args.calibrate:
        print("Refusing to run the investigation without --yes.")
        return 2

    world = LLMBrowserWorld(
        api_key, args.model,
        progress=lambda line: print(f"  [world] {line}", flush=True),
    )
    try:
        started = time.monotonic()
        if args.calibrate:
            run_calibration(world, args.seed, args.per_arm)
            print(f"Calibration used {world.trials_run} trials in "
                  f"{time.monotonic() - started:.0f}s.")
            return 0
        investigation = investigate(
            world, oracle, FACTORS, config, scenario_name="invoice-agent-browser"
        )
        elapsed = time.monotonic() - started
        print(f"\n{investigation.verdict.summary}")
        print(f"Elapsed: {elapsed:.0f}s over {investigation.verdict.trials_total} "
              "trials in one browser session")
        out_dir = Path(args.out)
        write_bundle(investigation, out_dir)
        print(f"Bundle written to {out_dir}")
        return 0
    finally:
        world.close()


if __name__ == "__main__":
    sys.exit(main())
