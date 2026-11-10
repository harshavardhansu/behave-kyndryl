import pytest
from fastapi.testclient import TestClient

from payment_api.app import PaymentSettings, RequestMetrics, create_app


def settings(release: str = "3.8.1") -> PaymentSettings:
    return PaymentSettings(
        database_url="postgresql+psycopg://payments:payments@localhost:5432/payments",
        release=release,
    )


def test_previous_release_does_not_register_feature_x():
    application = create_app(settings("previous"), engine=object(), initialize_database=False)

    assert "/payments/summary" not in {route.path for route in application.routes}
    assert application.title == "Payment API Sandbox"


def test_release_381_registers_feature_x():
    application = create_app(settings("3.8.1"), engine=object(), initialize_database=False)

    assert "/payments/summary" in {route.path for route in application.routes}


def test_payment_api_rejects_sqlite():
    config = PaymentSettings(database_url="sqlite:///./payments.db")

    with pytest.raises(ValueError, match="requires PostgreSQL"):
        create_app(config, engine=object(), initialize_database=False)


@pytest.mark.parametrize("pool_size, max_overflow, timeout", [(5, 0, 2), (20, 0, 2)])
def test_pool_settings_accept_required_failure_and_recovery_values(pool_size, max_overflow, timeout):
    config = PaymentSettings(
        database_url="postgresql+psycopg://payments:payments@localhost:5432/payments",
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=timeout,
    )

    config.validate()
    assert (config.pool_size, config.max_overflow, config.pool_timeout, config.hold_seconds) == (pool_size, max_overflow, timeout, 0.3)


def test_request_metrics_keep_a_bounded_latency_window():
    metrics = RequestMetrics()
    for index in range(10_001):
        metrics.record(500 if index == 0 else 200, float(index))

    result = metrics.snapshot()

    assert result["request_count"] == 10_001
    assert result["error_count"] == 1
    assert result["latency_ms"]["count"] == 10_000