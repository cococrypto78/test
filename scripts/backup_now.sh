#!/bin/bash
set -euo pipefail

# Source environment variables
source /opt/sales-agent/.env

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="/tmp/sales_agent_backup_${TIMESTAMP}.sql"
ENCRYPTED_FILE="${BACKUP_FILE}.enc"
BUCKET="${SCW_BUCKET_NAME:-sales-agent-backups}"
REGION="${SCW_REGION:-fr-par}"

echo "[Backup] Starting PostgreSQL backup at ${TIMESTAMP}"

# Extract connection details from DATABASE_URL
# Format: postgresql+psycopg2://user:pass@host:port/dbname
DB_URL="${DATABASE_URL/postgresql+psycopg2:\/\//postgresql://}"
PG_HOST=$(echo "$DATABASE_URL" | sed 's|.*@\(.*\):\([0-9]*\)/.*|\1|')
PG_PORT=$(echo "$DATABASE_URL" | sed 's|.*@.*:\([0-9]*\)/.*|\1|')
PG_USER=$(echo "$DATABASE_URL" | sed 's|.*://\(.*\):.*@.*|\1|')
PG_PASS=$(echo "$DATABASE_URL" | sed 's|.*://.*:\(.*\)@.*|\1|')
PG_DB=$(echo "$DATABASE_URL" | sed 's|.*/\(.*\)$|\1|')

export PGPASSWORD="${PG_PASS}"

# Dump database
pg_dump -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" "${PG_DB}" > "${BACKUP_FILE}"
echo "[Backup] pg_dump completed: $(du -sh ${BACKUP_FILE} | cut -f1)"

# Encrypt with AES-256-CBC
# Key derived from SCW_SECRET_KEY (must be set in .env)
ENCRYPTION_KEY="${SCW_SECRET_KEY:-changeme}"
openssl enc -aes-256-cbc -salt -pbkdf2 -iter 100000 \
  -pass pass:"${ENCRYPTION_KEY}" \
  -in "${BACKUP_FILE}" \
  -out "${ENCRYPTED_FILE}"

rm "${BACKUP_FILE}"
echo "[Backup] Encrypted: ${ENCRYPTED_FILE}"

# Upload to Scaleway Object Storage
if [ -n "${SCW_ACCESS_KEY}" ] && [ -n "${SCW_SECRET_KEY}" ]; then
  S3_ENDPOINT="https://s3.${REGION}.scw.cloud"
  S3_PATH="s3://${BUCKET}/backups/$(basename ${ENCRYPTED_FILE})"

  AWS_ACCESS_KEY_ID="${SCW_ACCESS_KEY}" \
  AWS_SECRET_ACCESS_KEY="${SCW_SECRET_KEY}" \
  aws s3 cp "${ENCRYPTED_FILE}" "${S3_PATH}" \
    --endpoint-url "${S3_ENDPOINT}" \
    --quiet

  echo "[Backup] Uploaded to ${S3_PATH}"

  # Cleanup backups older than 30 days
  AWS_ACCESS_KEY_ID="${SCW_ACCESS_KEY}" \
  AWS_SECRET_ACCESS_KEY="${SCW_SECRET_KEY}" \
  aws s3 ls "s3://${BUCKET}/backups/" \
    --endpoint-url "${S3_ENDPOINT}" | \
  while read -r date time size filename; do
    if [[ $(date -d "${date}" +%s) -lt $(date -d "30 days ago" +%s) ]]; then
      AWS_ACCESS_KEY_ID="${SCW_ACCESS_KEY}" \
      AWS_SECRET_ACCESS_KEY="${SCW_SECRET_KEY}" \
      aws s3 rm "s3://${BUCKET}/backups/${filename}" \
        --endpoint-url "${S3_ENDPOINT}" --quiet
      echo "[Backup] Deleted old backup: ${filename}"
    fi
  done
else
  echo "[Backup] WARNING: SCW credentials not set. Backup saved locally at ${ENCRYPTED_FILE}"
fi

rm -f "${ENCRYPTED_FILE}"
echo "[Backup] Done at $(date +%Y-%m-%dT%H:%M:%S)"
