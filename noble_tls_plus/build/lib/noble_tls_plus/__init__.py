import sys
from loguru import logger

# Default logging configuration
def configure_logging(log_level: str = "INFO"):
    """
    Configure the loguru logger.

    :param log_level: The logging level (e.g., "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL").
    """
    logger.remove()  # Remove the default logger
    logger.add(
        sys.stderr,
        level=log_level.upper(),
        format="{time} {level} {message}",
        backtrace=True,
        diagnose=True
    )

# Initialize with default log level
configure_logging()

from .client import NobleTLSClient
from .exceptions import MaxRetriesExceeded

__all__ = ['NobleTLSClient', 'MaxRetriesExceeded', 'configure_logging']