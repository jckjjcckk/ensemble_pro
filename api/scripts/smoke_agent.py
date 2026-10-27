"""Live smoke of the agent loop against the configured provider (LLM_PROVIDER=meta for Spark).

    cd api && LLM_PROVIDER=meta PYTHONPATH=. uv run scripts/smoke_agent.py

A three-page pretend score. The model must read every page, commit the parts of each one (the commit tool
refuses when the part count does not match the staves it was told), and finish. Prints the turn log, cost
and whether the loop ended as expected. No database.
"""
from __future__ import annotations

import asyncio
import json
import time

from app.agent import Refusal, Stop, ToolBox, run_agent

PAGES = {1: {"staves": 2, "hint": "the top staff is marked 'Violino', the bottom 'Violoncello'"},
         2: {"staves": 3, "hint": "a third staff appears, marked 'Viola', between the two"},
         3: {"staves": 3, "hint": "no staff labels on this page"}}

SYSTEM = """You are a music librarian reading a scanned score page by page.
Work only through tools, one call per turn. For every page: read_page, then commit_page with the part names
top to bottom (use the same names on later pages when a page carries no labels). When every page is
committed, call finish. If a page cannot be resolved, call ask_admin with a precise question."""


def main_box() -> ToolBox:
    b = ToolBox()

    @b.tool("read_page", "Read one page: staff count and what the labels say.", {"properties": {"page": {"type": "integer"}}, "required": ["page"]})
    def read_page(args, st):
        p = PAGES.get(int(args["page"]))
        if not p:
            return {"error": f"no page {args['page']}; the score has pages 1 to {len(PAGES)}"}
        st.scratch.setdefault("read", []).append(int(args["page"]))
        return {"page": int(args["page"]), "staves": p["staves"], "labels": p["hint"], "pages_total": len(PAGES)}

    @b.tool("commit_page", "Record the parts on a page, top to bottom.", {"properties": {"page": {"type": "integer"}, "parts": {"type": "array", "items": {"type": "string"}}}, "required": ["page", "parts"]}, commit=True)
    def commit_page(args, st):
        p = PAGES[int(args["page"])]
        if len(args["parts"]) != p["staves"]:
            raise Refusal(f"page {args['page']} has {p['staves']} staves but you named {len(args['parts'])} parts")
        st.scratch.setdefault("parts", {})[str(args["page"])] = args["parts"]
        return {"ok": True, "committed_pages": sorted(st.scratch["parts"])}

    @b.tool("ask_admin", "Ask the admin a question and stop.", {"properties": {"question": {"type": "string"}}, "required": ["question"]})
    def ask_admin(args, st):
        raise Stop("needs_review", question=args["question"])

    @b.tool("finish", "Finish once every page is committed.", {"properties": {"summary": {"type": "string"}}, "required": ["summary"]}, commit=True)
    def finish(args, st):
        missing = [p for p in PAGES if str(p) not in st.scratch.get("parts", {})]
        if missing:
            raise Refusal(f"pages {missing} are not committed yet")
        raise Stop("done", summary=args["summary"], parts=st.scratch["parts"])

    return b


async def main() -> None:
    t0 = time.time()
    st = await run_agent(system=SYSTEM, tools=main_box(), user_text="Read the score and commit every page.", max_turns=16, max_cost_usd=0.25)
    print("\n".join(st.log))
    print(f"status={st.status} turns={st.turn} cost=${st.cost_usd:.4f} tokens={st.input_tokens}+{st.output_tokens} {time.time()-t0:.1f}s")
    print("result:", json.dumps(st.result, ensure_ascii=False))
    ok = st.status == "done" and st.result.get("parts", {}).get("2", [])[1:2] == ["Viola"]
    print("SMOKE", "PASS" if ok else "FAIL")


asyncio.run(main())
