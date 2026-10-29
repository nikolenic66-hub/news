"""Daily DeepSeek quota and conservative spend accounting."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.models import DailyAPIUsage

logger = logging.getLogger(__name__)
_USAGE_LOCK_ID = 726100102
_ONE_MILLION = Decimal("1000000")
_COST_QUANTUM = Decimal("0.00000001")


class DeepSeekBudgetExceeded(RuntimeError):
    """The hard daily model-call or estimated-cost limit has been reached."""


@dataclass(frozen=True, slots=True)
class UsageReservation:
    usage_date: date
    reserved_cost_usd: Decimal


def _money(value: Decimal) -> Decimal:
    return value.quantize(_COST_QUANTUM, rounding=ROUND_HALF_UP)


def _cost(settings: Settings, input_tokens: int, output_tokens: int) -> Decimal:
    """Use configurable per-million prices; defaults use conservative peak rates."""
    amount = (
        Decimal(max(0, input_tokens)) * settings.deepseek_input_price_per_million_usd
        + Decimal(max(0, output_tokens)) * settings.deepseek_output_price_per_million_usd
    ) / _ONE_MILLION
    return _money(amount)


async def reserve_deepseek_call(
    sessions: async_sessionmaker,
    settings: Settings,
    prompt_characters: int,
) -> UsageReservation:
    """Reserve worst-case costs before calling DeepSeek, so the queue cannot spend unchecked."""
    local_day = datetime.now(ZoneInfo(settings.app_timezone)).date()
    # Two characters per token is intentionally conservative for mixed Russian/English text.
    estimated_input_tokens = max(800, (max(0, prompt_characters) + 1) // 2)
    reserved = _cost(settings, estimated_input_tokens, settings.deepseek_max_output_tokens)

    async with sessions() as session:
        async with session.begin():
            # Serialize reservations so overlapping scheduled invocations cannot bypass limits.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": _USAGE_LOCK_ID},
            )
            row = await session.get(DailyAPIUsage, local_day)
            if row is None:
                row = DailyAPIUsage(
                    usage_date=local_day,
                    request_count=0,
                    prompt_tokens=0,
                    completion_tokens=0,
                    estimated_cost_usd=Decimal("0"),
                )
                session.add(row)
                await session.flush()

            if row.request_count >= settings.max_deepseek_calls_per_day:
                raise DeepSeekBudgetExceeded("daily_call_limit_reached")

            current_cost = Decimal(row.estimated_cost_usd or 0)
            if current_cost + reserved > settings.deepseek_daily_budget_usd:
                raise DeepSeekBudgetExceeded("daily_budget_reached")

            row.request_count += 1
            row.estimated_cost_usd = _money(current_cost + reserved)
            logger.info(
                "DeepSeek budget reservation: calls=%d/%d, reserved=%.6f USD",
                row.request_count,
                settings.max_deepseek_calls_per_day,
                float(reserved),
            )

    return UsageReservation(local_day, reserved)


async def settle_deepseek_usage(
    sessions: async_sessionmaker,
    settings: Settings,
    reservation: UsageReservation,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """Replace the reservation with token-based cost using peak prices for a safety margin."""
    prompt_tokens = max(0, int(prompt_tokens))
    completion_tokens = max(0, int(completion_tokens))
    actual_cost = _cost(settings, prompt_tokens, completion_tokens)

    async with sessions() as session:
        async with session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": _USAGE_LOCK_ID},
            )
            row = await session.get(DailyAPIUsage, reservation.usage_date)
            if row is None:
                # A missing aggregate is unexpected. Do not silently lose accounting.
                logger.error("DeepSeek usage aggregate is missing for %s", reservation.usage_date)
                return

            current_cost = Decimal(row.estimated_cost_usd or 0)
            new_cost = max(Decimal("0"), current_cost - reservation.reserved_cost_usd) + actual_cost
            row.estimated_cost_usd = _money(new_cost)
            row.prompt_tokens += prompt_tokens
            row.completion_tokens += completion_tokens

            if new_cost > settings.deepseek_daily_budget_usd:
                logger.error(
                    "DeepSeek daily budget exceeded by actual usage: date=%s, amount=%.6f USD",
                    reservation.usage_date,
                    float(new_cost),
                )
            else:
                logger.info(
                    "DeepSeek usage settled: prompt=%d tokens, completion=%d tokens, "
                    "conservative daily estimate=%.6f USD",
                    prompt_tokens,
                    completion_tokens,
                    float(new_cost),
                )
