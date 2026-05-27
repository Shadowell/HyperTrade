from hypertrade.market.ingestion import IngestionHealth


def test_ingestion_health_enters_rest_fallback_after_repeated_ws_failures():
    health = IngestionHealth(max_failures_before_fallback=3)

    health.record_ws_failure()
    health.record_ws_failure()
    assert health.should_use_rest_fallback is False

    health.record_ws_failure()
    assert health.should_use_rest_fallback is True

    health.record_ws_success()
    assert health.should_use_rest_fallback is False
