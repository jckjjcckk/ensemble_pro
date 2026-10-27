"""Money. A shared hard cap (one row, one lock) is the limit; per-user counters are reporting.

`require_budget` runs before any model call and answers 402 when either the user's own budget or the shared
cap is spent. `charge` runs after the call, inside one Postgres transaction (`charge_usage`), so concurrent
requests cannot overspend the counter. Costs are computed by the caller from the provider's usage report.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, HTTPException

from .auth import CurrentUser, User
from .db import db


@dataclass(frozen=True)
class Spend:
    shared_spent: Decimal
    shared_cap: Decimal

    @property
    def exhausted(self) -> bool:
        return self.shared_spent >= self.shared_cap


def shared_spend() -> Spend:
    row = db().table("spend").select("spent_usd,cap_usd").eq("id", 1).single().execute().data
    return Spend(Decimal(str(row["spent_usd"])), Decimal(str(row["cap_usd"])))


def require_budget(user: CurrentUser) -> User:
    if user.over_budget:
        raise HTTPException(402, "Your budget for model calls is spent")
    if shared_spend().exhausted:
        raise HTTPException(402, "The shared budget for model calls is spent")
    return user


BudgetedUser = Annotated[User, Depends(require_budget)]


@dataclass(frozen=True)
class Charge:
    provider: str
    model: str
    kind: str          # 'claude' | 'spark' | 'sam' | 'voice'
    cost_usd: Decimal
    input_tokens: int = 0
    output_tokens: int = 0
    units: float = 0.0  # images, audio seconds, when tokens do not apply


def charge(user: User, c: Charge, job_id: str | None = None) -> dict:
    """Record one model call. Serialized in the database; returns the new totals."""
    res = db().rpc("charge_usage", {
        "p_user_id": user.id, "p_provider": c.provider, "p_model": c.model, "p_kind": c.kind,
        "p_input_tokens": c.input_tokens, "p_output_tokens": c.output_tokens, "p_units": c.units,
        "p_cost_usd": float(c.cost_usd), "p_job_id": job_id,
    }).execute()
    return res.data[0] if res.data else {}
