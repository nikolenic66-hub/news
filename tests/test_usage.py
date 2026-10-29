from decimal import Decimal
from types import SimpleNamespace

from app.usage import _cost


def test_cost_uses_configured_per_million_prices():
    settings = SimpleNamespace(
        deepseek_input_price_per_million_usd=Decimal("0.30"),
        deepseek_output_price_per_million_usd=Decimal("1.20"),
    )
    # 1,000 input tokens cost $0.0003 and 1,000 output tokens cost $0.0012.
    assert _cost(settings, 1_000, 1_000) == Decimal("0.00150000")


def test_cost_never_becomes_negative_for_empty_usage():
    settings = SimpleNamespace(
        deepseek_input_price_per_million_usd=Decimal("0.30"),
        deepseek_output_price_per_million_usd=Decimal("1.20"),
    )
    assert _cost(settings, -100, -1) == Decimal("0E-8")
