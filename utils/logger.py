import logging
import os
import sys
#from logging.handlers import TimedRotatingFileHandler
from concurrent_log_handler import ConcurrentRotatingFileHandler

# Ensure logs directory exists
LOG_DIR = os.path.join("data", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "tradingapp_debug.log")

class StreamToLogger:
    """
    Fake file-like stream object that redirects writes to a logger instance.
    """
    def __init__(self, logger, level=logging.ERROR):
        self.logger = logger
        self.level = level

    def write(self, message):
        message = message.strip()
        if message:  # avoid empty lines
            self.logger.log(self.level, message)

    def flush(self):
        pass

def get_logger(name: str = __name__) -> logging.Logger:
    """Return a logger configured to log to console and file."""

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:  # avoid duplicate handlers
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)

        # Rotating file handler: 5 MB per file, keep 5 backups
        file_handler = ConcurrentRotatingFileHandler(
            LOG_FILE,
            "a",
            maxBytes=5*1024*1024,
            backupCount=7,
            encoding='utf-8' 
        )
        file_handler.setLevel(logging.DEBUG)

        # Formatter
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)

        # Attach handlers
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    return logger