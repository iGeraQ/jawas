import os
from unittest.mock import patch


def test_settings_loads_required_fields():
    env = {
        "DATABASE_URL": "postgresql://test:test@localhost/test",
        "ANTHROPIC_API_KEY": "sk-test",
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "TELEGRAM_ADMIN_CHAT_ID": "456",
        "RAW_ITEMS_QUEUE_URL": "http://localhost:4566/000/raw",
        "APPROVED_DRAFTS_QUEUE_URL": "http://localhost:4566/000/approved",
        "DLQ_URL": "http://localhost:4566/000/dlq",
        "JINA_API_KEY": "jina-test",
    }
    with patch.dict(os.environ, env, clear=True):
        from importlib import reload
        import src.shared.config as m
        reload(m)
        s = m.Settings()
        assert s.database_url == "postgresql://test:test@localhost/test"
        assert s.relevance_threshold == 7


def test_settings_parses_comma_separated_profiles():
    env = {
        "DATABASE_URL": "postgresql://x",
        "ANTHROPIC_API_KEY": "k",
        "TELEGRAM_BOT_TOKEN": "t",
        "TELEGRAM_ADMIN_CHAT_ID": "1",
        "RAW_ITEMS_QUEUE_URL": "u",
        "APPROVED_DRAFTS_QUEUE_URL": "u",
        "DLQ_URL": "u",
        "JINA_API_KEY": "j",
        "X_PROFILES": "sama,karpathy,ylecun",
    }
    with patch.dict(os.environ, env, clear=True):
        from importlib import reload
        import src.shared.config as m
        reload(m)
        s = m.Settings()
        assert s.x_profiles == ["sama", "karpathy", "ylecun"]
