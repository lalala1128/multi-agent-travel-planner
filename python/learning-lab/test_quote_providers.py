import pytest

from quote_providers import DemoTravelProvider, ProviderConfigurationError, create_travel_provider


def test_demo_provider_marks_quote_source():
    quote = DemoTravelProvider().flight("北京", "首尔")
    assert quote.amount == 1800
    assert quote.provider == "demo"
    assert quote.quote_reference == "demo-flight-首尔"
    assert quote.quoted_at.tzinfo is not None


def test_non_demo_provider_fails_closed(monkeypatch):
    monkeypatch.setenv("TRAVEL_PROVIDER", "amadeus")
    provider = create_travel_provider()
    with pytest.raises(ProviderConfigurationError):
        provider.flight("北京", "首尔")
