from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median


@dataclass
class DailyCost:
    day: date
    amount: float


def settled_days(days: list[DailyCost], today: date) -> list[DailyCost]:
    """Cost Explorer lags 1-2 days and the 1st of the month carries a billing-boundary spike.
    Judging run-rate from either over-states or under-states the effect of a change."""
    cutoff = today - timedelta(days=2)
    return [d for d in days if d.day.day != 1 and d.day < cutoff]


def run_rate(days: list[DailyCost], today: date) -> float | None:
    usable = settled_days(days, today)
    if not usable:
        return None
    return round(median(d.amount for d in usable) * 30, 2)


def _ce_amount(row) -> float:
    return float(row["Total"]["UnblendedCost"]["Amount"]) if "Total" in row else 0.0


def monthly_trend(ce, months: int = 4, today: date | None = None) -> list[tuple[str, float]]:
    today = today or date.today()
    start = (today.replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1)
    r = ce.get_cost_and_usage(TimePeriod={"Start": start.isoformat(), "End": today.isoformat()},
                              Granularity="MONTHLY", Metrics=["UnblendedCost"])
    return [(x["TimePeriod"]["Start"][:7], round(_ce_amount(x), 2)) for x in r["ResultsByTime"]]


def by_service(ce, start: date, end: date, top: int = 15) -> list[tuple[str, float]]:
    r = ce.get_cost_and_usage(TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
                              Granularity="MONTHLY", Metrics=["UnblendedCost"],
                              GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}])
    totals: dict[str, float] = {}
    for period in r["ResultsByTime"]:
        for g in period["Groups"]:
            totals[g["Keys"][0]] = totals.get(g["Keys"][0], 0) + float(g["Metrics"]["UnblendedCost"]["Amount"])
    return sorted(((k, round(v, 2)) for k, v in totals.items()), key=lambda kv: -kv[1])[:top]


def daily(ce, start: date, end: date) -> list[DailyCost]:
    r = ce.get_cost_and_usage(TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
                              Granularity="DAILY", Metrics=["UnblendedCost"])
    return [DailyCost(date.fromisoformat(x["TimePeriod"]["Start"]), _ce_amount(x)) for x in r["ResultsByTime"]]
