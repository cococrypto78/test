#!/bin/bash
# Alerting quotidien : marge, queue Celery, disk usage
set -euo pipefail

source /opt/sales-agent/.env

ALERT_WEBHOOK="${WEBHOOK_URL:-}"
HOSTNAME=$(hostname)
ISSUES=()

# ── 1. Disk usage ─────────────────────────────────────────────────────────────
DISK_USAGE=$(df / --output=pcent | tail -1 | tr -d '%')
if [ "${DISK_USAGE}" -gt 80 ]; then
  ISSUES+=("⚠️ Disk usage at ${DISK_USAGE}% (threshold: 80%)")
fi

# ── 2. Celery queue length ────────────────────────────────────────────────────
REDIS_PASSWORD=$(echo "${REDIS_URL}" | sed 's|.*://:\(.*\)@.*|\1|')
REDIS_HOST=$(echo "${REDIS_URL}" | sed 's|.*@\(.*\):\([0-9]*\)/.*|\1|')
REDIS_PORT=$(echo "${REDIS_URL}" | sed 's|.*@.*:\([0-9]*\)/.*|\1|')

QUEUE_LEN=$(redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" -a "${REDIS_PASSWORD}" \
  LLEN celery 2>/dev/null || echo "0")
if [ "${QUEUE_LEN}" -gt 1000 ]; then
  ISSUES+=("⚠️ Celery queue has ${QUEUE_LEN} tasks (threshold: 1000)")
fi

# ── 3. Cost margin check ──────────────────────────────────────────────────────
PG_HOST=$(echo "$DATABASE_URL" | sed 's|.*@\(.*\):\([0-9]*\)/.*|\1|')
PG_PORT=$(echo "$DATABASE_URL" | sed 's|.*@.*:\([0-9]*\)/.*|\1|')
PG_USER=$(echo "$DATABASE_URL" | sed 's|.*://\(.*\):.*@.*|\1|')
PG_PASS=$(echo "$DATABASE_URL" | sed 's|.*://.*:\(.*\)@.*|\1|')
PG_DB=$(echo "$DATABASE_URL" | sed 's|.*/\(.*\)$|\1|')

export PGPASSWORD="${PG_PASS}"

COST_TODAY=$(psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" "${PG_DB}" \
  -t -c "SELECT COALESCE(SUM(cost_usd), 0) FROM api_usage WHERE ts >= NOW() - INTERVAL '24 hours';" 2>/dev/null | tr -d ' ')
echo "[Alerting] Cost last 24h: \$${COST_TODAY}"

# ── 4. Services health ────────────────────────────────────────────────────────
if ! systemctl is-active --quiet postgresql@16-main; then
  ISSUES+=("🔴 PostgreSQL is DOWN")
fi
if ! systemctl is-active --quiet redis-server; then
  ISSUES+=("🔴 Redis is DOWN")
fi
if ! docker compose -f /opt/sales-agent/docker-compose.production.yml ps --services --filter status=running | grep -q web; then
  ISSUES+=("🔴 FastAPI web service is DOWN")
fi

# ── Send alert ────────────────────────────────────────────────────────────────
if [ ${#ISSUES[@]} -gt 0 ] && [ -n "${ALERT_WEBHOOK}" ]; then
  MESSAGE="*[${HOSTNAME}] Sales Agent Alert — $(date +%Y-%m-%d)*\n"
  for issue in "${ISSUES[@]}"; do
    MESSAGE+="${issue}\n"
  done

  curl -s -X POST "${ALERT_WEBHOOK}" \
    -H "Content-Type: application/json" \
    -d "{\"text\": \"${MESSAGE}\"}" > /dev/null
  echo "[Alerting] Alerts sent: ${#ISSUES[@]}"
elif [ ${#ISSUES[@]} -eq 0 ]; then
  echo "[Alerting] All checks OK"
else
  echo "[Alerting] ${#ISSUES[@]} issues but no webhook configured"
  for issue in "${ISSUES[@]}"; do echo "  $issue"; done
fi
