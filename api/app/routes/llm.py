from fastapi import APIRouter
from pydantic import BaseModel

from ..llm import complete, model_name
from ..settings import settings
from ..spend import BudgetedUser, charge

router = APIRouter()


class Probe(BaseModel):
    text: str = "Reply with the single word: ok"


@router.post("/llm/probe")
async def probe(body: Probe, user: BudgetedUser) -> dict:
    """The smallest possible model call, to prove the chain: token → profile → budget → provider → charge."""
    c = await complete(body.text, effort="low", max_tokens=64)
    totals = charge(user, c.charge)
    return {"provider": settings.llm_provider, "model": model_name(), "text": c.text, "cost_usd": float(c.charge.cost_usd), "totals": totals}
