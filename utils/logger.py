import sys
from loguru import logger as _logger
from config.settings import settings

_logger.remove()

_logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level=settings.log_level,
    colorize=True,
)

_logger.add(
    "logs/agent_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="30 days",
    compression="gz",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} - {message}",
    level=settings.log_level,
    enqueue=True,
)

logger = _logger
