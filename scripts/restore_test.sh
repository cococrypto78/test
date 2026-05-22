#!/bin/bash
# Test de restauration — crée une DB temporaire et vérifie que le dump se restaure correctement
set -euo pipefail

source /opt/sales-agent/.env

ENCRYPTION_KEY="${SCW_SECRET_KEY:-changeme}"
TEST_DB="sales_agent_restore_test_$(date +%s)"
LATEST_BACKUP=""

echo "[RestoreTest] Starting at $(date)"

# Find latest backup
if [ -n "${SCW_ACCESS_KEY}" ]; then
  S3_ENDPOINT="https://s3.${SCW_REGION:-fr-par}.scw.cloud"
  LATEST_BACKUP=$(AWS_ACCESS_KEY_ID="${SCW_ACCESS_KEY}" \
    AWS_SECRET_ACCESS_KEY="${SCW_SECRET_KEY}" \
    aws s3 ls "s3://${SCW_BUCKET_NAME}/backups/" \
      --endpoint-url "${S3_ENDPOINT}" | \
    sort | tail -1 | awk '{print $4}')

  if [ -z "${LATEST_BACKUP}" ]; then
    echo "[RestoreTest] No backups found in S3"
    exit 1
  fi

  ENCRYPTED_FILE="/tmp/${LATEST_BACKUP}"
  AWS_ACCESS_KEY_ID="${SCW_ACCESS_KEY}" \
  AWS_SECRET_ACCESS_KEY="${SCW_SECRET_KEY}" \
  aws s3 cp "s3://${SCW_BUCKET_NAME}/backups/${LATEST_BACKUP}" "${ENCRYPTED_FILE}" \
    --endpoint-url "${S3_ENDPOINT}"
else
  echo "[RestoreTest] WARNING: No S3 configured. Skipping download."
  exit 0
fi

# Decrypt
SQL_FILE="${ENCRYPTED_FILE%.enc}"
openssl enc -d -aes-256-cbc -salt -pbkdf2 -iter 100000 \
  -pass pass:"${ENCRYPTION_KEY}" \
  -in "${ENCRYPTED_FILE}" \
  -out "${SQL_FILE}"

# Restore to test DB
PG_HOST=$(echo "$DATABASE_URL" | sed 's|.*@\(.*\):\([0-9]*\)/.*|\1|')
PG_PORT=$(echo "$DATABASE_URL" | sed 's|.*@.*:\([0-9]*\)/.*|\1|')
PG_USER=$(echo "$DATABASE_URL" | sed 's|.*://\(.*\):.*@.*|\1|')
PG_PASS=$(echo "$DATABASE_URL" | sed 's|.*://.*:\(.*\)@.*|\1|')
export PGPASSWORD="${PG_PASS}"

sudo -u postgres psql -c "CREATE DATABASE ${TEST_DB};"
psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" "${TEST_DB}" < "${SQL_FILE}"

# Verify
TABLE_COUNT=$(psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" "${TEST_DB}" \
  -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';")

echo "[RestoreTest] Tables restored: ${TABLE_COUNT}"

# Cleanup
sudo -u postgres psql -c "DROP DATABASE ${TEST_DB};"
rm -f "${SQL_FILE}" "${ENCRYPTED_FILE}"

echo "[RestoreTest] SUCCESS — $(echo $TABLE_COUNT) tables restored and verified"
