# DEPLOYMENT LOG — Sales Agent SaaS
**Serveur** : Scaleway sales-agent-prod, Ubuntu 22.04 LTS  
**Déployé par** : Claude Code (claude-sonnet-4-6)  
**Date** : 2026-05-19

---

## PHASE 1 — Server Hardening ✅ COMPLETE (21:44 UTC)

- `apt update && apt upgrade -y` — 6 paquets upgradés
- UFW : ports 22, 80, 443 depuis internet ; 5432/6379 autorisés depuis Docker uniquement
- SSH : `PermitRootLogin no`, `PasswordAuthentication no` — `/etc/ssh/sshd_config`
- fail2ban : jails `sshd` + `nginx-http-auth`, bantime=3600s, maxretry=5
- unattended-upgrades : patches sécurité auto (jammy-security)
- Swap 5.5 GB déjà présent

---

## PHASE 2 — Stack de base ✅ COMPLETE (21:55 UTC)

- PostgreSQL 16.14 (pgdg) + pgvector 0.8.2, Redis 6.0.16 avec auth
- Python 3.12.13 (PPA deadsnakes), Docker 29.5.1 déjà présent
- **Architecture** : Coolify conservé comme runtime (Traefik gère SSL/routing)
- PostgreSQL écoute sur `*` ; pg_hba.conf : accès uniquement depuis 10.0.0.0/8 et 172.16.0.0/12
- Redis écoute sur 127.0.0.1 + interfaces Docker
- UFW bloque 5432 et 6379 depuis internet (allow uniquement depuis Docker CIDRs)

---

## PHASE 3 — Clone et configuration ✅ COMPLETE (21:56 UTC)

- Repo cloné depuis `https://github.com/cococrypto78/test.git`
- `.env.example` : suppression LINKEDIN_*, INSTAGRAM_*, TIKTOK_* credentials (remplacés par Postmark/X API/Meta Graph)
- `.env` créé, chmod 600, PG_PASSWORD/REDIS_PASSWORD/SECRET_KEY générés
- `requirements.txt` mis à jour : supprimé playwright/instagrapi/fake-useragent/aiosmtplib
- Venv `.venv` Python 3.12 créé

---

## PHASE 4 — Schéma DB multi-tenant ✅ COMPLETE (22:05 UTC)

- `crm/models.py` réécrit : 12 tables avec tenant_id non-null + indexes
- `alembic upgrade head` : b2371fba953b — 13 tables créées
- Index ivfflat sur `voice_embeddings(embedding vector_cosine_ops)`
- pgvector 0.8.2 actif

---

## PHASE 5 — Channel adapters ✅ COMPLETE (22:10 UTC)

- `channels/base.py` : interface abstraite (supports_server_send, send, prepare_paste)
- **LinkedIn** : paste mode UNIQUEMENT (`channels/linkedin/adapter.py`)
- **Twitter/X** : API officielle v2, OAuth 1.0a, tweepy (`channels/twitter/adapter.py`)
- **Instagram** : Meta Graph API + fallback paste (`channels/instagram/adapter.py`)
- **TikTok** : paste mode UNIQUEMENT (`channels/tiktok/adapter.py`)
- **Email** : Postmark HTTP API, domaine dédié (`channels/email/adapter.py`)

---

## PHASE 6 — Couches IA ✅ COMPLETE (22:10 UTC)

- `ai/training.py` : build_system_prompt (cache_control=ephemeral), few-shot, pgvector retrieval
- `ai/drafting.py` : draft_message (Sonnet 4.6), classify_reply (Haiku 4.5), logging api_usage

---

## PHASE 7 — Tâches Celery ✅ COMPLETE (22:10 UTC)

- `tasks/celery_app.py` : beat schedules
- `tasks/draft_campaign.py`, `send_approved.py`, `check_replies.py`
- `tasks/classify_reply.py`, `refresh_voice_examples.py`, `embed_message.py`

---

## PHASE 8 — Webhooks ✅ COMPLETE (22:11 UTC)

- `GET /healthz` — DB + Redis + Celery
- `GET /metrics` — Prometheus format
- `POST /webhooks/postmark/inbound|bounce`
- `POST /webhooks/stripe` — vérification signature
- `POST/GET /webhooks/twitter/events` — CRC challenge inclus
- `POST/GET /webhooks/meta` — hub.challenge inclus

---

## PHASE 9 — Docker Compose ✅ COMPLETE (22:18 UTC)

- `Dockerfile` : Python 3.12-slim, sans playwright/chromium
- `docker-compose.production.yml` : web (4 workers uvicorn), worker (Celery), beat
- Réseau Coolify, labels Traefik pour SSL auto
- `systemctl enable/start sales-agent` : active
- `curl http://127.0.0.1:8001/healthz` → 200 : DB✓ Redis✓ Celery(1 worker)✓

---

## PHASE 10 — Monitoring & Backups ✅ COMPLETE (22:19 UTC)

- `scripts/backup_now.sh` — pg_dump + AES-256-CBC → Scaleway Object Storage
- `scripts/restore_test.sh` — test restauration
- `scripts/alerting.sh` — disk/queue/cost/services + webhook
- Cron 03:00 backup, 08:00 alerting
- Logrotate 14 jours

---

## ACCEPTANCE CRITERIA

| # | Critère | Status |
|---|---------|--------|
| 1 | UFW = seulement 22/80/443 depuis internet | ✅ PASS |
| 2 | `systemctl status sales-agent` = active | ✅ PASS |
| 3 | `curl https://app.<domaine>/healthz` = 200 | ⏳ Domaine + DNS requis |
| 4 | `alembic current` = head | ✅ PASS (b2371fba953b) |
| 5 | pgvector extension active | ✅ PASS (0.8.2) |
| 6 | Draft message → status=drafted | ⏳ ANTHROPIC_API_KEY requis |
| 7 | Email test Postmark | ⏳ POSTMARK_SERVER_TOKEN requis |
| 8 | `.env` sans LINKEDIN_*PASSWORD etc. | ✅ PASS |
| 9 | Backup sur Scaleway Object Storage | ⏳ SCW credentials requis |
| 10 | Sentry event test | ⏳ SENTRY_DSN requis |

---

## NOTES TECHNIQUES

- `DATABASE_URL` dans `.env` utilise `host.docker.internal` (résolu en 10.0.0.1 dans Docker)
- `MIGRATION_DATABASE_URL` dans `.env` utilise `localhost` (pour `alembic upgrade head` depuis le host)
- Coolify Traefik gère SSL — configurer le domaine dans le panel Coolify
- Credentials PostgreSQL et Redis dans `/root/.pg_credentials_temp` — à supprimer après avoir sécurisé ailleurs
