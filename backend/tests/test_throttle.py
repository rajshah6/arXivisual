"""Unit tests for the /api/process cost-protection primitives."""

from api.throttle import RecentJobs, SlidingWindowLimiter


class TestSlidingWindowLimiter:
    def test_allows_up_to_max_then_denies(self):
        lim = SlidingWindowLimiter(max_events=3, window_seconds=60)
        now = 1000.0
        assert lim.allow("ip1", now)[0] is True
        assert lim.allow("ip1", now + 1)[0] is True
        assert lim.allow("ip1", now + 2)[0] is True
        allowed, retry_after = lim.allow("ip1", now + 3)
        assert allowed is False
        # Oldest event at t=1000 expires at t=1060 -> ~57s (+1 rounding) left.
        assert 57 <= retry_after <= 59

    def test_window_expiry_frees_capacity(self):
        lim = SlidingWindowLimiter(max_events=1, window_seconds=10)
        assert lim.allow("k", 0.0)[0] is True
        assert lim.allow("k", 5.0)[0] is False
        assert lim.allow("k", 10.5)[0] is True  # first event aged out

    def test_keys_are_independent(self):
        lim = SlidingWindowLimiter(max_events=1, window_seconds=60)
        assert lim.allow("a", 0.0)[0] is True
        assert lim.allow("b", 0.0)[0] is True  # different key unaffected
        assert lim.allow("a", 1.0)[0] is False

    def test_zero_max_disables_limiter(self):
        lim = SlidingWindowLimiter(max_events=0, window_seconds=60)
        for i in range(100):
            assert lim.allow("k", float(i))[0] is True

    def test_retry_after_is_at_least_one_second(self):
        lim = SlidingWindowLimiter(max_events=1, window_seconds=0.5)
        assert lim.allow("k", 0.0)[0] is True
        allowed, retry_after = lim.allow("k", 0.4)
        assert allowed is False
        assert retry_after >= 1


class TestRecentJobs:
    def test_put_get_roundtrip(self):
        rj = RecentJobs(ttl_seconds=600)
        rj.put("1706.03762", "job_abc", now=0.0)
        assert rj.get("1706.03762", now=100.0) == "job_abc"

    def test_ttl_expiry(self):
        rj = RecentJobs(ttl_seconds=600)
        rj.put("1706.03762", "job_abc", now=0.0)
        assert rj.get("1706.03762", now=601.0) is None

    def test_clear_removes_entry(self):
        rj = RecentJobs(ttl_seconds=600)
        rj.put("1706.03762", "job_abc", now=0.0)
        rj.clear("1706.03762")
        assert rj.get("1706.03762", now=1.0) is None

    def test_unknown_paper_returns_none(self):
        assert RecentJobs().get("nope") is None
