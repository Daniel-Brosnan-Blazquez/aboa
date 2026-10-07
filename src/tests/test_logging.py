"""
Tests for ABOA logging configuration.
"""

import logging
import os
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

from aboa import logging as logging_module


class TestLogging(unittest.TestCase):
    """
    Unit tests for logger setup and rotating handler behavior.
    """

    def setUp(self):
        """
        Preserve environment and redirect module log output to a temporary path.
        """
        self.environment = os.environ.copy()
        self.original_log_path = logging_module.log_path
        self.log_root = Path(tempfile.mkdtemp(prefix="aboa_logging_test_"))
        logging_module.log_path = str(self.log_root)
        os.environ["ABOA_LOG_LEVEL"] = "DEBUG"
        os.environ["ABOA_STREAM_LOG"] = "1"
        os.environ["ABOA_LOG_MAX_BYTES"] = "1"
        os.environ["ABOA_LOG_MAX_BACKUP"] = "1"
        self.logger_name = "aboa.tests.logging.{}".format(uuid.uuid4())
        self.logger_names = [self.logger_name, logging_module.__name__]

    def tearDown(self):
        """
        Remove handlers, restore environment, and delete temporary logs.
        """
        for logger_name in self.logger_names:
            logger = logging.getLogger(logger_name)
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()
        logging_module.log_path = self.original_log_path
        os.environ.clear()
        os.environ.update(self.environment)
        shutil.rmtree(str(self.log_root), ignore_errors=True)

    def test_log_configuration_adds_stream_file_handler_and_custom_level(self):
        """
        Configure stream and file handlers and exercise rotating rollover.
        """
        wrapper = logging_module.Log(name=self.logger_name, log_name="aboa_test.log")
        wrapper.define_logging_configuration(self.logger_name)
        stream_handlers = [
            handler
            for handler in wrapper.logger.handlers
            if type(handler) == logging.StreamHandler
        ]
        file_handlers = [
            handler
            for handler in wrapper.logger.handlers
            if type(handler) == logging_module.RotatingFileHandlerAllUsers
        ]

        wrapper.logger.debugp("processor-level detail")
        assert wrapper.logger.level == logging.DEBUG
        wrapper.logger.setLevel(logging.CRITICAL)
        wrapper.logger.debugp("processor-level detail hidden by level")
        default_wrapper = logging_module.Log(name=None, log_name="aboa_default_test.log")
        file_handlers[0].doRollover()

        assert len(stream_handlers) == 1
        assert len(file_handlers) == 1
        assert Path(file_handlers[0].baseFilename).exists()
        assert default_wrapper.logger.name == logging_module.__name__
