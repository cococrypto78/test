from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from config.settings import settings


def _async_url(url: str) -> str:
    """Convert psycopg2 URL to asyncpg. Replace host.docker.internal with localhost when not in Docker."""
    import socket
    url = url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    try:
        socket.gethostbyname("host.docker.internal")
    except socket.gaierror:
        # Not running inside Docker — use localhost instead
        url = url.replace("host.docker.internal", "localhost", 1)
    return url


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    _async_url(settings.database_url),
    echo=settings.is_development,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

async_session_factory = AsyncSessionLocal


async def get_db():
    """FastAPI dependency: yields a session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_session():
    """FastAPI dependency alias for get_db (used in routes via Depends)."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def session_context():
    """Async context manager for non-FastAPI use (tasks, CLI): async with session_context() as session:"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
