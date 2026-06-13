# Multi-Network Publisher — Design Spec

**Date:** 2026-06-12
**Branch:** feat/phase-1-foundation
**Status:** Approved

## Goal

Extend the publisher to support Bluesky, LinkedIn, and Facebook in addition to X, using a registry-based architecture where adding a new social network requires only creating one new file — no changes to `main.py`.

## Current state and problems

- `SocialNetworkProvider.publish()` returns `str` (post ID only); URL and post count are built X-specifically in `main.py`.
- `DailyLimitReached` and the daily limit check logic live in `main.py`, hardcoded for X.
- `PublishedPost.tweet_count` is an X-specific column name in the shared model.
- `TokenBucket` (rate limiter) lives in `src/enricher/providers/base.py`, unavailable to publisher providers.
- `PROVIDERS` dict in `main.py` requires manual edits for every new network.

## Architecture

### Core abstractions — `src/publisher/base.py`

```python
@dataclass
class PublishResult:
    post_id: str
    url: str
    post_count: int = 1

class RateLimitExceeded(Exception):
    def __init__(self, wait_seconds: int):
        self.wait_seconds = wait_seconds

class SocialNetworkProvider(ABC):
    @abstractmethod
    def publish(self, content: str) -> PublishResult: ...

_REGISTRY: dict[str, type[SocialNetworkProvider]] = {}

def register_publisher(name: str):
    def decorator(cls):
        _REGISTRY[name] = cls
        return cls
    return decorator

def get_provider(name: str) -> SocialNetworkProvider:
    if name not in _REGISTRY:
        raise ValueError(f"Unknown publisher: {name}")
    return _REGISTRY[name]()
```

### Shared rate limiter — `src/shared/rate_limit.py`

`TokenBucket` moves from `src/enricher/providers/base.py` to `src/shared/rate_limit.py`. Both enricher providers and publisher providers import it from there. The enricher providers are updated to use the new import path.

### Generic `main.py`

`main.py` imports all provider modules at the top (their `@register_publisher` decorators self-register into `_REGISTRY`). After that, `main.py` contains zero network-specific logic:

```python
import src.publisher.providers.x        # noqa: F401
import src.publisher.providers.bluesky  # noqa: F401
import src.publisher.providers.linkedin # noqa: F401
import src.publisher.providers.facebook # noqa: F401
```

`process_message()` calls `get_provider(provider_name).publish(content)` and uses the returned `PublishResult` to populate `PublishedPost`. The `run()` loop catches `RateLimitExceeded` generically and sleeps for `e.wait_seconds`.

The X-specific daily limit check moves inside `XProvider.publish()`: it queries the DB via `get_session()`, calculates the wait, and raises `RateLimitExceeded(wait_seconds=...)` before calling the Twitter API.

### Provider implementations

#### `XProvider` (updated)

- Moves daily limit check (DB query) into `publish()`.
- Raises `RateLimitExceeded` instead of `DailyLimitReached`.
- Returns `PublishResult(post_id=first_tweet_id, url=f"https://x.com/i/web/status/{first_tweet_id}", post_count=len(parts))`.

#### `BlueskyProvider` (new)

- SDK: `atproto`.
- 300-char limit per post; thread support via reply chain (same pattern as X).
- Class-level `TokenBucket(rate=300, per=3600.0)` (conservative vs Bluesky's 5000/day).
- Auth: `BLUESKY_HANDLE` + `BLUESKY_APP_PASSWORD` (app password, not account password).
- The AT URI has the form `at://did:plc:xxx/app.bsky.feed.post/{rkey}`. The rkey is extracted for the URL.
- URL: `https://bsky.app/profile/{handle}/post/{rkey}`.
- `post_id` stored in DB is the full AT URI (stable identifier). Returns `PublishResult(post_id=at_uri, url=..., post_count=len(parts))`.

#### `LinkedInProvider` (new)

- Transport: `requests` (direct REST to `https://api.linkedin.com/v2/`).
- Single post up to 3000 chars; no threading.
- Auth: `LINKEDIN_ACCESS_TOKEN` (manually issued OAuth 2.0 token; LinkedIn Organization Page tokens do not expire unless revoked) + `LINKEDIN_AUTHOR_URN` (e.g. `urn:li:organization:xxx`).
- Class-level `TokenBucket(rate=80, per=86400.0)` (conservative vs LinkedIn's ~150/day limit).
- The API returns a post URN like `urn:li:share:7xxxxxxxxxx`. URL: `https://www.linkedin.com/feed/update/urn:li:share:{id}/`.
- Returns `PublishResult(post_id=urn, url=..., post_count=1)`.

#### `FacebookProvider` (new)

- Transport: `requests` (Graph API `https://graph.facebook.com/v19.0/`).
- Single post up to 63 206 chars; no threading.
- Auth: `FACEBOOK_PAGE_ID` + `FACEBOOK_PAGE_ACCESS_TOKEN` (Page token, never expires unless permissions revoked).
- Class-level `TokenBucket(rate=150, per=3600.0)`.
- Graph API returns `{page_id}_{object_id}`. URL: `https://www.facebook.com/{page_id}/posts/{object_id}`.
- Returns `PublishResult(post_id=f"{page_id}_{object_id}", url=..., post_count=1)`.

### Database migration

Rename `published_posts.tweet_count → post_count`. Single Alembic migration — no type or index change required. All existing rows are valid (values remain the same).

### Config (`src/shared/config.py`)

New optional fields (all default to `""`):

```python
bluesky_handle: str = ""
bluesky_app_password: str = ""
linkedin_access_token: str = ""
linkedin_author_urn: str = ""
facebook_page_id: str = ""
facebook_page_access_token: str = ""
```

### Docker Compose

Three new services following the same pattern as `publisher-x`:

```yaml
publisher-bluesky:
  build: .
  command: python -m src.publisher.main bluesky
  env_file: .env
  depends_on: [postgres, localstack]

publisher-linkedin:
  build: .
  command: python -m src.publisher.main linkedin
  env_file: .env
  depends_on: [postgres, localstack]

publisher-facebook:
  build: .
  command: python -m src.publisher.main facebook
  env_file: .env
  depends_on: [postgres, localstack]
```

### Synthesizer updates (`src/enricher/`)

The synthesizer already calls `synthesize(..., networks: list[str])`. Updates needed:

1. `enricher/main.py`: add `"bluesky"`, `"linkedin"`, `"facebook"` to the networks list passed to the synthesizer.
2. Synthesizer prompts: add per-network instructions:
   - **bluesky**: same tone as X, max 300 chars per post, thread-friendly.
   - **linkedin**: professional tone, single post up to 1500 chars, include context and takeaway.
   - **facebook**: conversational, single post up to 1000 chars, accessible language.

## File change summary

| File | Action |
|---|---|
| `src/shared/rate_limit.py` | Create — move `TokenBucket` here |
| `src/enricher/providers/base.py` | Update — import `TokenBucket` from shared |
| `src/enricher/providers/anthropic.py` | Update — import path for `TokenBucket` |
| `src/enricher/providers/gemini.py` | Update — import path for `TokenBucket` |
| `src/enricher/providers/openai.py` | Update — import path for `TokenBucket` |
| `src/publisher/base.py` | Rewrite — add `PublishResult`, `RateLimitExceeded`, registry |
| `src/publisher/main.py` | Rewrite — fully generic, catches `RateLimitExceeded` |
| `src/publisher/providers/x.py` | Update — move daily limit check in, return `PublishResult` |
| `src/publisher/providers/bluesky.py` | Create |
| `src/publisher/providers/linkedin.py` | Create |
| `src/publisher/providers/facebook.py` | Create |
| `src/shared/config.py` | Update — new credential fields |
| `src/shared/models.py` | Update — rename `tweet_count → post_count` |
| `migrations/versions/xxxx_rename_tweet_count.py` | Create |
| `docker-compose.yml` | Update — add 3 publisher services |
| `src/enricher/main.py` | Update — add 3 networks to synthesizer call |
| `src/enricher/providers/anthropic.py` | Update — synthesizer prompts for new networks |
| `src/enricher/providers/gemini.py` | Update — synthesizer prompts for new networks |
| `src/enricher/providers/openai.py` | Update — synthesizer prompts for new networks |
| `.env.example` | Update — new credential vars |
| `tests/publisher/test_bluesky_provider.py` | Create |
| `tests/publisher/test_linkedin_provider.py` | Create |
| `tests/publisher/test_facebook_provider.py` | Create |
| `tests/publisher/test_x_provider.py` | Update — adapt to `PublishResult` |

## Extension contract

To add a fifth network (e.g. Threads):
1. Create `src/publisher/providers/threads.py` with `@register_publisher("threads")`.
2. Add the import in `main.py`.
3. Add credentials to `config.py` and `.env.example`.
4. Add service to `docker-compose.yml`.
5. Add network to the synthesizer's networks list and its prompt.

No other files change.
