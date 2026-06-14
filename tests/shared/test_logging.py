from src.shared.logging import setup_logging, logger


def test_setup_logging_runs_without_error():
    setup_logging()
    assert logger is not None


def test_logger_can_emit_info():
    setup_logging()
    logger.info("test_event", key="value")
