"""
Logging definition.

module aboa
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from aboa.engine.functions import get_log_path, read_configuration

config = read_configuration()
log_path = get_log_path()


class RotatingFileHandlerAllUsers(RotatingFileHandler):
    """
    Rotating file handler that keeps rotated log files writable by all users.
    """

    def doRollover(self):
        """
        Rotate the log file and relax permissions on the new active file.
        """
        RotatingFileHandler.doRollover(self)
        os.chmod(self.baseFilename, 0o666)


class Log():
    """
    Configure and expose an ABOA logger.

    The logger uses rotating file handlers and supports environment
    overrides for level, stream logging, maximum size, and backup count.
    """

    def __init__(self, name=None, log_name="aboa_engine.log"):
        """
        Build a logger wrapper.

        :param name: logger name
        :type name: str or None
        :param log_name: log file name
        :type log_name: str
        """
        self.log_name = log_name
        # Add a custom logging level for debug messages inside processors.
        self._add_new_level("DEBUGP", 15)
        self.define_logging_configuration(name)

    def define_logging_configuration(self, name=None):
        """
        Configure handlers, formatter, and log level.

        :param name: logger name
        :type name: str or None
        """
        if name is None:
            name = __name__
        self.logger = logging.getLogger(name)
        if "ABOA_LOG_LEVEL" in os.environ:
            self.logger.setLevel(getattr(logging, os.environ["ABOA_LOG_LEVEL"]))
        else:
            self.logger.setLevel(getattr(logging, config["LOG"]["LEVEL"]))

        formatter = logging.Formatter(
            "%(levelname)s\t; (%(asctime)s.%(msecs)03d) ; %(name)s(%(lineno)d) [%(process)d] -> %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

        stream_handlers = [handler for handler in self.logger.handlers if type(handler) == logging.StreamHandler]
        if "ABOA_STREAM_LOG" in os.environ and len(stream_handlers) < 1:
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            self.logger.addHandler(stream_handler)

        max_bytes = int(os.environ.get("ABOA_LOG_MAX_BYTES", config["LOG"]["MAX_BYTES"]))
        max_backup = int(os.environ.get("ABOA_LOG_MAX_BACKUP", config["LOG"]["MAX_BACKUP"]))
        os.makedirs(log_path, exist_ok=True)

        file_handlers = [handler for handler in self.logger.handlers if type(handler) == RotatingFileHandlerAllUsers]
        if len(file_handlers) < 1:
            file_handler = RotatingFileHandlerAllUsers(os.path.join(log_path, self.log_name), maxBytes=max_bytes, backupCount=max_backup)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    def _add_new_level(self, name, level):
        """
        Add a custom logging level to the logging module.

        :param name: level name
        :type name: str
        :param level: numeric logging level
        :type level: int
        """
        logging.addLevelName(level, name)

        def log_for_level(self, message, *args, **kwargs):
            """
            Log a message using the custom level when it is enabled.
            """
            if self.isEnabledFor(level):
                self._log(level, message, args, **kwargs)

        setattr(logging, name, level)
        setattr(logging.getLoggerClass(), name.lower(), log_for_level)
