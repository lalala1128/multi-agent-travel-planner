import fakeredis
import pytest

from rate_limiter import RateLimitExceeded, RateLimiter


def test_rate_limiter_rejects_after_window_quota():
    limiter = RateLimiter(
        fakeredis.FakeRedis(decode_responses=True),
        max_requests=2,
        window_seconds=60,
    )
    limiter.check("client-a")
    limiter.check("client-a")
    with pytest.raises(RateLimitExceeded) as error:
        limiter.check("client-a")
    assert error.value.retry_after > 0


def test_rate_limiter_uses_distinct_hashed_keys():
    assert RateLimiter.key("client-a") != RateLimiter.key("client-b")


def test_zero_limit_disables_rate_limiting():
    limiter = RateLimiter(
        fakeredis.FakeRedis(decode_responses=True),
        max_requests=0,
        window_seconds=60,
    )
    for _ in range(3):
        limiter.check("client-a")
