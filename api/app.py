import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import AsyncGenerator

import stripe
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext

from config.settings import settings
from crm.database import init_db, session_context
from utils.logger import logger

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_ws_clients: list[WebSocket] = []
_processed_events: dict[str, float] = {}  # Simple dedup cache


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    await init_db()
    if settings.sentry_dsn:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        sentry_sdk.init(dsn=settings.sentry_dsn, integrations=[FastApiIntegration()])
    logger.info("Sales Agent API started")
    yield
    logger.info("Sales Agent API stopped")


app = FastAPI(
    title="Sales Agent SaaS API",
    version="2.0.0",
    description="Multi-tenant multi-channel AI sales prospecting platform",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth helpers ─────────────────────────────────────────────────────────────

def _create_token(data: dict, expires_delta: timedelta = timedelta(hours=24)) -> str:
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + expires_delta
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return username
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def _dedup(event_id: str, ttl_seconds: int = 86400) -> bool:
    """Returns True if event is new (not seen before), False if duplicate."""
    now = time.time()
    _processed_events[event_id] = _processed_events.get(event_id, 0)
    if _processed_events[event_id] > 0:
        return False
    _processed_events[event_id] = now
    # Cleanup old entries
    expired = [k for k, v in _processed_events.items() if now - v > ttl_seconds]
    for k in expired:
        del _processed_events[k]
    return True


# ── Auth ─────────────────────────────────────────────────────────────────────

@app.post("/auth/token", tags=["auth"])
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # Basic admin auth — replace with tenant-aware auth in production
    from passlib.context import CryptContext
    ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Use /api/auth/login with tenant credentials",
    )


# ── Healthcheck ───────────────────────────────────────────────────────────────

@app.get("/healthz", tags=["monitoring"])
async def healthz():
    import asyncpg
    from redis.asyncio import Redis

    checks = {}

    # DB check
    try:
        db_url = settings.database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
        conn = await asyncpg.connect(dsn=db_url, timeout=3)
        await conn.fetchval("SELECT 1")
        await conn.close()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Redis check
    try:
        r = Redis.from_url(settings.redis_url, socket_connect_timeout=3)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    # Celery worker check
    try:
        from tasks.celery_app import app as celery_app
        inspector = celery_app.control.inspect(timeout=2)
        active = inspector.active()
        checks["celery_workers"] = len(active) if active else 0
    except Exception:
        checks["celery_workers"] = "unknown"

    status_code = 200 if all(v == "ok" for k, v in checks.items() if k != "celery_workers") else 503
    return {"status": "ok" if status_code == 200 else "degraded", "checks": checks, "timestamp": datetime.utcnow().isoformat()}


@app.get("/metrics", tags=["monitoring"])
async def metrics():
    """Prometheus-compatible metrics endpoint."""
    from sqlalchemy import select, func
    from crm.models import Message, MessageStatus, ApiUsage

    lines = []
    try:
        async with session_context() as session:
            total_msgs = await session.scalar(select(func.count(Message.id)))
            drafted = await session.scalar(select(func.count(Message.id)).where(Message.status == MessageStatus.drafted))
            sent = await session.scalar(select(func.count(Message.id)).where(Message.status == MessageStatus.sent))
            total_cost = await session.scalar(select(func.sum(ApiUsage.cost_usd))) or 0.0

        lines = [
            f"# HELP sales_agent_messages_total Total messages",
            f"sales_agent_messages_total {total_msgs}",
            f"# HELP sales_agent_messages_drafted Messages in drafted status",
            f"sales_agent_messages_drafted {drafted}",
            f"# HELP sales_agent_messages_sent Messages sent",
            f"sales_agent_messages_sent {sent}",
            f"# HELP sales_agent_anthropic_cost_usd Total Anthropic cost in USD",
            f"sales_agent_anthropic_cost_usd {total_cost:.4f}",
        ]
    except Exception as e:
        lines = [f"# ERROR {e}"]

    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


# ── Webhooks ─────────────────────────────────────────────────────────────────

@app.post("/webhooks/postmark/inbound", tags=["webhooks"])
async def postmark_inbound(request: Request):
    """Réponses email entrantes via Postmark inbound."""
    body = await request.json()
    event_id = body.get("MessageID", "") or body.get("message_id", "")

    if not _dedup(f"postmark_in_{event_id}"):
        return {"status": "duplicate"}

    from_email = body.get("From", "")
    text_body = body.get("TextBody", "")
    html_stripped = body.get("StrippedTextReply", text_body)

    if from_email and html_stripped:
        from tasks.classify_reply import classify_incoming_reply
        from crm.models import Message, MessageStatus
        from sqlalchemy import select

        async with session_context() as session:
            # Find message by recipient email
            result = await session.execute(
                select(Message).where(
                    Message.status == MessageStatus.sent,
                ).limit(1)
            )
            msg = result.scalar_one_or_none()
            if msg:
                classify_incoming_reply.delay(str(msg.tenant_id), str(msg.id), html_stripped)

    return {"status": "ok"}


@app.post("/webhooks/postmark/bounce", tags=["webhooks"])
async def postmark_bounce(request: Request):
    """Bounces et spam complaints Postmark."""
    body = await request.json()
    bounce_type = body.get("Type", "")
    email = body.get("Email", "")
    logger.warning(f"[Webhook] Postmark bounce type={bounce_type} email={email}")
    return {"status": "ok"}


@app.post("/webhooks/stripe", tags=["webhooks"])
async def stripe_webhook(request: Request):
    """Événements billing Stripe (vérification de signature obligatoire)."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Stripe webhook secret not configured")

    try:
        event = stripe.Webhook.construct_event(payload, sig, settings.stripe_webhook_secret)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")

    event_id = event["id"]
    if not _dedup(f"stripe_{event_id}"):
        return {"status": "duplicate"}

    event_type = event["type"]
    logger.info(f"[Webhook] Stripe event={event_type} id={event_id}")

    if event_type == "customer.subscription.updated":
        data = event["data"]["object"]
        customer_id = data.get("customer")
        new_status = data.get("status")
        logger.info(f"[Stripe] Subscription updated: customer={customer_id} status={new_status}")

    elif event_type == "customer.subscription.deleted":
        data = event["data"]["object"]
        customer_id = data.get("customer")
        logger.warning(f"[Stripe] Subscription cancelled: customer={customer_id}")

    return {"status": "ok"}


@app.post("/webhooks/twitter/events", tags=["webhooks"])
async def twitter_events(request: Request):
    """Replies DM Twitter via Account Activity API."""
    # CRC validation for Twitter webhook
    crc_token = request.query_params.get("crc_token")
    if crc_token:
        import base64
        mac = hmac.new(settings.x_api_secret.encode(), crc_token.encode(), hashlib.sha256)
        response_token = base64.b64encode(mac.digest()).decode()
        return {"response_token": f"sha256={response_token}"}

    body = await request.json()
    for dm_event in body.get("direct_message_events", []):
        event_id = dm_event.get("id", "")
        if not _dedup(f"twitter_dm_{event_id}"):
            continue
        sender_id = dm_event.get("message_create", {}).get("sender_id", "")
        text = dm_event.get("message_create", {}).get("message_data", {}).get("text", "")
        if text and sender_id:
            logger.info(f"[Twitter] DM reply from sender_id={sender_id}")
            # TODO: match sender_id to prospect and trigger classify_reply

    return {"status": "ok"}


@app.get("/webhooks/twitter/events", tags=["webhooks"])
async def twitter_crc(request: Request):
    """CRC challenge for Twitter Account Activity API."""
    crc_token = request.query_params.get("crc_token", "")
    if not crc_token:
        raise HTTPException(status_code=400, detail="crc_token required")
    import base64
    mac = hmac.new(settings.x_api_secret.encode(), crc_token.encode(), hashlib.sha256)
    response_token = base64.b64encode(mac.digest()).decode()
    return {"response_token": f"sha256={response_token}"}


@app.post("/webhooks/meta", tags=["webhooks"])
async def meta_events(request: Request):
    """Events Instagram/Messenger via Meta Graph API."""
    # Verify X-Hub-Signature-256
    sig_header = request.headers.get("X-Hub-Signature-256", "")
    body = await request.body()

    app_secret = settings.meta_graph_access_token  # Use Meta App Secret in production
    if app_secret and sig_header:
        expected = "sha256=" + hmac.new(
            app_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig_header, expected):
            raise HTTPException(status_code=403, detail="Invalid Meta signature")

    data = json.loads(body)
    for entry in data.get("entry", []):
        for messaging in entry.get("messaging", []):
            event_id = messaging.get("message", {}).get("mid", "")
            if not _dedup(f"meta_{event_id}"):
                continue
            sender_id = messaging.get("sender", {}).get("id", "")
            text = messaging.get("message", {}).get("text", "")
            if text and sender_id:
                logger.info(f"[Meta] IG message from sender_id={sender_id}")
                # TODO: match sender_id to prospect and trigger classify_reply

    return {"status": "ok"}


@app.get("/webhooks/meta", tags=["webhooks"])
async def meta_verify(request: Request):
    """Webhook verification challenge for Meta."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if mode == "subscribe" and token == settings.secret_key[:16]:
        return int(challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/activity")
async def activity_feed(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)


async def broadcast_activity(event: dict) -> None:
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_text(json.dumps(event))
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


# ── Messages API ─────────────────────────────────────────────────────────────

@app.post("/api/messages/{message_id}/mark-sent", tags=["messages"])
async def mark_message_sent(message_id: str, request: Request):
    """Marque un message paste-mode comme envoyé par l'utilisateur."""
    from crm.models import Message, MessageStatus
    from sqlalchemy import select
    from datetime import datetime

    body = await request.json()
    tenant_id = body.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id required")

    async with session_context() as session:
        result = await session.execute(
            select(Message).where(
                Message.id == message_id,
                Message.tenant_id == tenant_id,
            )
        )
        msg = result.scalar_one_or_none()
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")

        msg.status = MessageStatus.sent
        msg.sent_at = datetime.utcnow()
        await session.commit()

    return {"status": "ok", "message_id": message_id}
