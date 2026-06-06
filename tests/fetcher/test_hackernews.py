from unittest.mock import patch, MagicMock
from src.fetcher.sources.hackernews import fetch_hn_items


def test_fetch_hn_filters_by_keywords():
    stories = {
        1: {"id": 1, "title": "New GPT model released", "url": "https://hn.com/1", "type": "story"},
        2: {"id": 2, "title": "Weekend cooking tips", "url": "https://hn.com/2", "type": "story"},
        3: {"id": 3, "title": "Claude 4 by Anthropic", "url": "https://hn.com/3", "type": "story"},
    }

    def mock_get(url, **kwargs):
        resp = MagicMock()
        if "topstories" in url:
            resp.json.return_value = [1, 2, 3]
        else:
            item_id = int(url.split("/")[-1].replace(".json", ""))
            resp.json.return_value = stories[item_id]
        return resp

    with patch("httpx.get", side_effect=mock_get):
        items = fetch_hn_items(keywords=["GPT", "Claude", "Anthropic"])

    titles = [i["title"] for i in items]
    assert "New GPT model released" in titles
    assert "Claude 4 by Anthropic" in titles
    assert "Weekend cooking tips" not in titles
