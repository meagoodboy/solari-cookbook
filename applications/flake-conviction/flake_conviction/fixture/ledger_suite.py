"""The suite under test: three checks on a ledger report, one planted defect.
summary_line iterates a set, so its order follows the per-process string hash
seed. The expected value is not hand-written: the build stage keeps one run of
`--record` under PYTHONHASHSEED=0, which is how this defect reaches a real
suite. FIXTURE_TEST_ORDER shuffles the checks so that "randomized test order"
is a suspect that genuinely varies between trials."""

import os
import random
import sys

ENTRIES = [{"currency": "usd", "amount": 10}, {"currency": "eur", "amount": 20},
           {"currency": "gbp", "amount": 30}, {"currency": "jpy", "amount": 40}]
RATES = {"usd": 1.0, "eur": 1.09, "gbp": 1.27, "jpy": 0.0067}


def totals(entries):
    sums = {}
    for entry in entries:
        sums[entry["currency"]] = sums.get(entry["currency"], 0.0) + float(entry["amount"])
    return sums


def summary_line(entries):
    sums = totals(entries)
    seen = {code for code in sums}
    return " ".join("%s=%.2f" % (code, sums[code]) for code in seen)


def to_usd(entries):
    return round(sum(float(e["amount"]) * RATES[e["currency"]] for e in entries), 2)


def check_recorded_summary():
    with open("expected.txt", encoding="utf-8") as fh:
        expected = fh.read().strip()
    if summary_line(ENTRIES) != expected:
        raise AssertionError("%r != recorded %r" % (summary_line(ENTRIES), expected))


def check_every_currency_named():
    line = summary_line(ENTRIES)
    if not all(e["currency"] in line for e in ENTRIES):
        raise AssertionError("a currency is missing from %r" % line)


def check_usd_total_order_independent():
    if to_usd(ENTRIES) != to_usd(list(reversed(ENTRIES))):
        raise AssertionError("to_usd depends on entry order")


def main(argv):
    if argv[1:] == ["--record"]:
        print(summary_line(ENTRIES))
        return 0
    checks = [check_recorded_summary, check_every_currency_named, check_usd_total_order_independent]
    order = os.environ.get("FIXTURE_TEST_ORDER", "0")
    if order != "0":
        random.Random(int(order)).shuffle(checks)
    failed = 0
    for check in checks:
        try:
            check()
            print("ok   " + check.__name__)
        except AssertionError as exc:
            failed += 1
            print("FAIL " + check.__name__ + ": " + str(exc))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
