import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import AsyncGenerator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext

from config.settings import settings
from crm.database import init_db
from api.routes import prospects, campaigns, agents, handoffs
from api.schemas import TokenOut
from utils.logger import logger

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_ws_clients: list[WebSocket] = []


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    await init_db()
    logger.info("Sales Agents API started")
    yield
    logger.info("Sales Agents API stopped")


app = FastAPI(
    title="Autonomous Sales Agents API",
    version="1.0.0",
    description="Multi-channel autonomous sales prospecting system powered by Claude AI",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.post("/auth/token", response_model=TokenOut, tags=["auth"])
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    if form_data.username != settings.api_username or not pwd_context.verify(form_data.password, settings.api_password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect credentials")
    token = _create_token({"sub": form_data.username})
    return TokenOut(access_token=token)


app.include_router(prospects.router, dependencies=[Depends(get_current_user)])
app.include_router(campaigns.router, dependencies=[Depends(get_current_user)])
app.include_router(agents.router, dependencies=[Depends(get_current_user)])
app.include_router(handoffs.router, dependencies=[Depends(get_current_user)])


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.websocket("/ws/activity")
async def activity_feed(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        _ws_clients.remove(websocket)


async def broadcast_activity(event: dict) -> None:
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_text(json.dumps(event))
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)
