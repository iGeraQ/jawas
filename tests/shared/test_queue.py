from unittest.mock import MagicMock, patch

from src.shared.queue import delete_message, receive_messages, send_message


def _mock_client():
    client = MagicMock()
    client.send_message.return_value = {}
    client.receive_message.return_value = {"Messages": [{"Body": '{"item_id": "1"}', "ReceiptHandle": "rh-1"}]}
    client.delete_message.return_value = {}
    return client


def test_send_message():
    mock_client = _mock_client()
    with patch("src.shared.queue._client", return_value=mock_client), \
         patch("src.shared.queue.settings"):
        send_message("http://localhost/queue", {"item_id": "abc"})

    mock_client.send_message.assert_called_once()
    call_kwargs = mock_client.send_message.call_args[1]
    assert call_kwargs["QueueUrl"] == "http://localhost/queue"
    assert '"item_id"' in call_kwargs["MessageBody"]


def test_receive_messages_returns_list():
    mock_client = _mock_client()
    with patch("src.shared.queue._client", return_value=mock_client), \
         patch("src.shared.queue.settings"):
        result = receive_messages("http://localhost/queue")

    assert len(result) == 1
    assert result[0]["ReceiptHandle"] == "rh-1"


def test_receive_messages_empty_response():
    mock_client = MagicMock()
    mock_client.receive_message.return_value = {}

    with patch("src.shared.queue._client", return_value=mock_client), \
         patch("src.shared.queue.settings"):
        result = receive_messages("http://localhost/queue")

    assert result == []


def test_delete_message():
    mock_client = _mock_client()
    with patch("src.shared.queue._client", return_value=mock_client), \
         patch("src.shared.queue.settings"):
        delete_message("http://localhost/queue", "rh-abc")

    mock_client.delete_message.assert_called_once_with(
        QueueUrl="http://localhost/queue", ReceiptHandle="rh-abc"
    )


def test_receive_messages_logs_count():
    import structlog.testing
    mock_client = _mock_client()
    with patch("src.shared.queue._client", return_value=mock_client), \
         patch("src.shared.queue.settings"), \
         structlog.testing.capture_logs() as cap_logs:
        receive_messages("http://localhost/queue")
    debug_logs = [l for l in cap_logs if l.get("event") == "messages_received"]
    assert len(debug_logs) == 1
    assert debug_logs[0]["count"] == 1
    assert "queue" in debug_logs[0]


def test_delete_message_logs_debug():
    import structlog.testing
    mock_client = _mock_client()
    with patch("src.shared.queue._client", return_value=mock_client), \
         patch("src.shared.queue.settings"), \
         structlog.testing.capture_logs() as cap_logs:
        delete_message("http://localhost/queue", "rh-abc")
    debug_logs = [l for l in cap_logs if l.get("event") == "message_deleted"]
    assert len(debug_logs) == 1
    assert "queue" in debug_logs[0]
