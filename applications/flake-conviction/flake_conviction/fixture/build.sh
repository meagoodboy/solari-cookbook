set -euo pipefail
# Static: nothing is interpolated into this file. The suite arrives in
# SUITE_SOURCE and is written with printf '%s', which keeps its bytes.
rm -rf "$FIXTURE_DIR"
mkdir -p "$FIXTURE_DIR"
cd "$FIXTURE_DIR"
printf '%s' "$SUITE_SOURCE" > ledger_suite.py
PYTHONHASHSEED=0 python3 ledger_suite.py --record > expected.txt
echo "recorded: $(cat expected.txt)"
if ! PYTHONHASHSEED=0 FIXTURE_TEST_ORDER=0 python3 ledger_suite.py > /dev/null; then
  echo "FIXTURE BROKEN: the neutral arm failed"; exit 1
fi
echo "neutral arm passed"
fails=0
for seed in 1 2 3 4 5 6 7 8 9 10 11 12; do
  PYTHONHASHSEED="$seed" FIXTURE_TEST_ORDER=0 python3 ledger_suite.py > /dev/null || fails=$((fails + 1))
done
echo "active arm: $fails of 12 seeds failed"
if [ "$fails" -lt 6 ]; then
  echo "FIXTURE TOO WEAK: $fails of 12; the trial budget cannot find this"; exit 1
fi
# Unquoted on purpose: the locale decoy is two assignments in one word.
for decoy in FIXTURE_TEST_ORDER=987654321 TZ=Asia/Kolkata "LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8"; do
  if ! env PYTHONHASHSEED=0 $decoy python3 ledger_suite.py > /dev/null; then
    echo "FIXTURE BROKEN: $decoy changed the outcome with the seed pinned"; exit 1
  fi
  echo "decoy inert: $decoy"
done
