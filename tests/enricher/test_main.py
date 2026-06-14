from unittest.mock import MagicMock, patch

import pytest

from src.enricher.main import process_message


def _make_session(item=None):
    session = MagicMock()
    session.get.return_value = item
    return session


def _make_item(score_override=None):
    item = MagicMock()
    item.id = "item-uuid"
    item.url = "https://example.com/article"
    item.title = "Claude 3.5 released"
    item.raw_content = "Some raw text"
    item.status = "pending"
    item.relevance_score = None
    return item


def test_process_message_missing_item_id():
    with patch("src.enricher.main.get_session"):
        process_message({})


def test_process_message_item_not_found():
    mock_session = _make_session(item=None)
    with patch("src.enricher.main.get_session", return_value=mock_session):
        process_message({"item_id": "missing-id"})
    mock_session.close.assert_called_once()


def test_process_message_discards_below_threshold():
    item = _make_item()
    mock_session = _make_session(item=item)

    mock_provider = MagicMock()
    mock_provider.score.return_value = 3

    with patch("src.enricher.main.get_session", return_value=mock_session), \
         patch("src.enricher.main.resolve_url", return_value="https://example.com/article"), \
         patch("src.enricher.main.extract_content", return_value="article text"), \
         patch("src.enricher.main.get_provider", return_value=mock_provider), \
         patch("src.enricher.main.settings") as mock_settings:
        mock_settings.relevance_threshold = 7
        process_message({"item_id": "item-uuid"})

    assert item.status == "discarded"
    mock_session.commit.assert_called_once()
    mock_provider.synthesize.assert_not_called()


def test_process_message_creates_drafts():
    item = _make_item()
    mock_session = _make_session(item=item)

    mock_provider = MagicMock()
    mock_provider.score.return_value = 9
    mock_provider.synthesize.return_value = {
        "x": "Tweet content",
        "linkedin": "LinkedIn content",
    }

    with patch("src.enricher.main.get_session", return_value=mock_session), \
         patch("src.enricher.main.resolve_url", return_value="https://example.com/article"), \
         patch("src.enricher.main.extract_content", return_value="article text"), \
         patch("src.enricher.main.get_provider", return_value=mock_provider), \
         patch("src.enricher.main.settings") as mock_settings:
        mock_settings.relevance_threshold = 7
        process_message({"item_id": "item-uuid"})

    assert item.status == "enriched"
    assert mock_session.add.call_count == 2
    mock_session.commit.assert_called_once()


def test_process_message_no_drafts_generated():
    item = _make_item()
    mock_session = _make_session(item=item)

    mock_provider = MagicMock()
    mock_provider.score.return_value = 9
    mock_provider.synthesize.return_value = {}

    with patch("src.enricher.main.get_session", return_value=mock_session), \
         patch("src.enricher.main.resolve_url", return_value="https://example.com/article"), \
         patch("src.enricher.main.extract_content", return_value="article text"), \
         patch("src.enricher.main.get_provider", return_value=mock_provider), \
         patch("src.enricher.main.settings") as mock_settings:
        mock_settings.relevance_threshold = 7
        process_message({"item_id": "item-uuid"})

    assert item.status == "discarded"
    mock_session.commit.assert_called_once()


def test_process_message_exception_triggers_rollback():
    item = _make_item()
    mock_session = _make_session(item=item)
    mock_session.commit.side_effect = RuntimeError("db error")

    mock_provider = MagicMock()
    mock_provider.score.return_value = 9
    mock_provider.synthesize.return_value = {"x": "Tweet"}

    with patch("src.enricher.main.get_session", return_value=mock_session), \
         patch("src.enricher.main.resolve_url", return_value="https://example.com"), \
         patch("src.enricher.main.extract_content", return_value="text"), \
         patch("src.enricher.main.get_provider", return_value=mock_provider), \
         patch("src.enricher.main.settings") as mock_settings:
        mock_settings.relevance_threshold = 7
        with pytest.raises(RuntimeError):
            process_message({"item_id": "item-uuid"})

    mock_session.rollback.assert_called_once()
    mock_session.close.assert_called_once()
