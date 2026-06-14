import pytest
from unittest.mock import MagicMock, patch

from src.publisher.base import PublishResult, RateLimitExceeded
from src.publisher.main import process_message


def _make_draft(network="x", draft_id="draft-uuid"):
    draft = MagicMock()
    draft.id = draft_id
    draft.network = network
    draft.content = "Post content"
    draft.edited_content = None
    return draft


def test_process_message_missing_draft_id():
    with patch("src.publisher.main.get_session"):
        process_message({}, "x")


def test_process_message_draft_not_found():
    mock_session = MagicMock()
    mock_session.get.return_value = None

    with patch("src.publisher.main.get_session", return_value=mock_session):
        process_message({"draft_id": "missing"}, "x")

    mock_session.close.assert_called_once()


def test_process_message_wrong_network():
    draft = _make_draft(network="linkedin")
    mock_session = MagicMock()
    mock_session.get.return_value = draft

    with patch("src.publisher.main.get_session", return_value=mock_session):
        process_message({"draft_id": "draft-uuid"}, "x")

    mock_session.close.assert_called_once()
    mock_session.commit.assert_not_called()


def test_process_message_already_published():
    draft = _make_draft()
    existing_post = MagicMock()
    existing_post.network_post_id = "existing-post-id"

    mock_session = MagicMock()
    mock_session.get.return_value = draft
    mock_session.execute.return_value.scalar_one_or_none.return_value = existing_post

    with patch("src.publisher.main.get_session", return_value=mock_session):
        process_message({"draft_id": "draft-uuid"}, "x")

    mock_session.commit.assert_not_called()


def test_process_message_rate_limit_raises():
    draft = _make_draft()
    mock_session = MagicMock()
    mock_session.get.return_value = draft
    mock_session.execute.return_value.scalar_one_or_none.return_value = None

    mock_provider = MagicMock()
    mock_provider.publish.side_effect = RateLimitExceeded(wait_seconds=60)

    with patch("src.publisher.main.get_session", return_value=mock_session), \
         patch("src.publisher.main.get_provider", return_value=mock_provider):
        with pytest.raises(RateLimitExceeded):
            process_message({"draft_id": "draft-uuid"}, "x")

    mock_session.rollback.assert_called_once()


def test_process_message_uses_edited_content():
    draft = _make_draft()
    draft.edited_content = "Edited tweet"

    mock_session = MagicMock()
    mock_session.get.return_value = draft
    mock_session.execute.return_value.scalar_one_or_none.return_value = None

    mock_provider = MagicMock()
    mock_provider.publish.return_value = PublishResult(
        post_id="tweet-1", url="https://x.com/i/web/status/tweet-1", post_count=1
    )

    with patch("src.publisher.main.get_session", return_value=mock_session), \
         patch("src.publisher.main.get_provider", return_value=mock_provider):
        process_message({"draft_id": "draft-uuid"}, "x")

    mock_provider.publish.assert_called_once_with("Edited tweet")
