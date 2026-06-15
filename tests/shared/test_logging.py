import logging
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import structlog
import structlog.testing


def _mock_settings(log_level="INFO", log_file_path=None, metrics_port=9100):
    m = MagicMock()
    m.log_level = log_level
    m.log_file_path = log_file_path
    m.metrics_port = metrics_port
    m.relevance_threshold = 7
    m.fetch_interval_hours = 2
    m.ai_provider = "anthropic"
    return m


@pytest.fixture(autouse=True)
def reset_structlog():
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


def test_setup_logging_binds_service():
    with patch("src.shared.logging.settings", _mock_settings()):
        from src.shared.logging import setup_logging, logger
        setup_logging("fetcher")

    with structlog.testing.capture_logs() as cap_logs:
        from src.shared.logging import logger
        logger.info("test_event")

    assert cap_logs[0]["service"] == "fetcher"
    assert cap_logs[0]["event"] == "test_event"


def test_debug_level_emits_debug_events():
    with patch("src.shared.logging.settings", _mock_settings(log_level="DEBUG")):
        from src.shared.logging import setup_logging, logger
        setup_logging("test")

    with structlog.testing.capture_logs() as cap_logs:
        from src.shared.logging import logger
        logger.debug("debug_event")

    assert any(l["event"] == "debug_event" for l in cap_logs)


def test_info_level_suppresses_debug_events():
    with patch("src.shared.logging.settings", _mock_settings(log_level="INFO")):
        from src.shared.logging import setup_logging, logger
        setup_logging("test")

    with structlog.testing.capture_logs() as cap_logs:
        from src.shared.logging import logger
        logger.debug("should_not_appear")

    assert not any(l["event"] == "should_not_appear" for l in cap_logs)


def test_log_startup_config_emits_info():
    with patch("src.shared.logging.settings", _mock_settings()):
        from src.shared.logging import setup_logging, log_startup_config
        setup_logging("test")

    with structlog.testing.capture_logs() as cap_logs:
        from src.shared.logging import log_startup_config
        log_startup_config()

    assert any(l["event"] == "service_startup_config" for l in cap_logs)


def test_log_file_created_when_path_set():
    with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
        path = f.name

    try:
        with patch("src.shared.logging.settings", _mock_settings(log_file_path=path)):
            import importlib
            import src.shared.logging as log_mod
            importlib.reload(log_mod)
            log_mod.setup_logging("test")
            log_mod.logger.info("file_test_event")
            if log_mod._file_handler:
                log_mod._file_handler.flush()

        with open(path) as f:
            content = f.read()
        assert "file_test_event" in content
    finally:
        os.unlink(path)
