from origin_core.providers.breaker import BreakerState, CircuitBreaker


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_opens_after_threshold_and_recovers_after_cooldown() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(threshold=2, cooldown_s=10, clock=clock)
    breaker.record_failure()
    assert breaker.allow()
    breaker.record_failure()
    assert breaker.state is BreakerState.OPEN
    assert not breaker.allow()

    clock.now = 10
    assert breaker.state is BreakerState.HALF_OPEN
    assert breaker.allow()
    breaker.record_success()
    assert breaker.state is BreakerState.CLOSED


def test_failed_trial_reopens() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(threshold=1, cooldown_s=5, clock=clock)
    breaker.record_failure()
    clock.now = 5
    assert breaker.state is BreakerState.HALF_OPEN
    breaker.record_failure()
    assert breaker.state is BreakerState.OPEN
    clock.now = 9
    assert not breaker.allow()


def test_success_resets_failure_count() -> None:
    breaker = CircuitBreaker(threshold=2, clock=FakeClock())
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    assert breaker.state is BreakerState.CLOSED
