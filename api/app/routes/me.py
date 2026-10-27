from fastapi import APIRouter

from ..auth import CurrentUser
from ..db import db
from ..spend import shared_spend

router = APIRouter()


@router.get("/me")
def me(user: CurrentUser) -> dict:
    """The account, its libraries (own + each ensemble with role and seat), and what it may still spend."""
    rows = db().table("members").select("id,role,part,ensemble_id,ensembles(id,name)").eq("user_id", user.id).execute().data
    shared = shared_spend()
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "memberships": [
            {"member_id": m["id"], "ensemble_id": m["ensemble_id"], "ensemble_name": (m.get("ensembles") or {}).get("name"), "role": m["role"], "part": m["part"]}
            for m in rows
        ],
        "budget": {
            "budget_usd": float(user.budget_usd), "spent_usd": float(user.spent_usd),
            "shared_cap_usd": float(shared.shared_cap), "shared_spent_usd": float(shared.shared_spent),
            "can_call_models": not user.over_budget and not shared.exhausted,
        },
    }
