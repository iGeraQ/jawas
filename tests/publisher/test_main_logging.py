from unittest.mock import MagicMock, patch
import uuid

import structlog
import structlog.testing
import pytest


@pytest.fixture(autouse=True)
def reset_structlog():
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


def test_process_message_logs_publish_attempt():
    from src.publisher.main import process_message
    from src.publisher.base import PublishResult

    draft_id = str(uuid.uuid4())
    mock_draft = MagicMock()
    mock_draft.network = "x"
    mock_draft.content = "Hello world"
    mock_draft.edited_content = None

    mock_result = PublishResult(post_id="tweet-1", post_count=1, url="https://x.com/i/web/status/1")

    with patch("src.publisher.main.get_session") as mock_get_session, \
         patch("src.publisher.main.get_provider") as mock_get_provider:

        mock_session = MagicMock()
        mock_session.get.return_value = mock_draft
        mock_session.execute.return_value.scalar_one_or_none.return_value = None
        mock_get_session.return_value = mock_session

        mock_provider = MagicMock()
        mock_provider.publish.return_value = mock_result
        mock_get_provider.return_value = mock_provider

        with structlog.testing.capture_logs() as cap_logs:
            process_message({"draft_id": draft_id}, "x")

    attempt_events = [l for l in cap_logs if l.get("event") == "publish_attempt"]
    assert len(attempt_events) == 1
    assert attempt_events[0]["network"] == "x"
    assert attempt_events[0]["draft_id"] == draft_id
