#!/usr/bin/env bash
set -euo pipefail

APP_URL="${1:-http://127.0.0.1:8000}"
DURATION_SECS="${2:-40}"

echo "=== [1/3] Verifying Baseline Workload Health at ${APP_URL} ==="
BASELINE_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${APP_URL}/healthz" || echo "FAIL")
if [ "$BASELINE_STATUS" != "200" ]; then
  echo "Warning: Workload not responding with 200 on /healthz (status: ${BASELINE_STATUS})."
fi

echo "=== [2/3] Injecting Synthetic Chaos (Toggling Error Rate Spike) ==="
INJECT_RESP=$(curl -s -X POST "${APP_URL}/chaos/inject")
echo "Injection Response: ${INJECT_RESP}"

echo "=== [3/3] Driving Request Traffic to Burn Error Budget (${DURATION_SECS}s) ==="
END_TIME=$((SECONDS + DURATION_SECS))
COUNT_500=0
COUNT_TOTAL=0

while [ $SECONDS -lt $END_TIME ]; do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "${APP_URL}/" || echo "ERR")
  COUNT_TOTAL=$((COUNT_TOTAL + 1))
  if [ "$CODE" == "500" ]; then
    COUNT_500=$((COUNT_500 + 1))
  fi
  printf "\rSent: %d requests | 500 Errors: %d | Status: %s" "$COUNT_TOTAL" "$COUNT_500" "$CODE"
  sleep 0.2
done

echo ""
echo "=== Chaos Load Complete ==="
echo "Total Requests: ${COUNT_TOTAL}"
echo "500 Status Responses: ${COUNT_500}"
echo "Error Ratio: $(awk "BEGIN {print ($COUNT_500 / $COUNT_TOTAL) * 100}")%"
