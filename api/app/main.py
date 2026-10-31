import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import convert, jobs, llm, me, scores, voice
from .settings import settings

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The job worker runs inside the API process unless WORKER=0 (e.g. a second process that only serves).
    # With it, a Realtime listener wakes the loop when a job is inserted (WORKER_WAKE, default on; the poll stays).
    stop = asyncio.Event()
    tasks = []
    if os.environ.get("WORKER", "1") != "0" and settings.supabase_url:
        from .worker import loop
        wake = None
        if settings.worker_wake and settings.supabase_secret_key:
            from .wake import Wake
            w = Wake(settings.supabase_url, settings.supabase_secret_key)
            wake = w.event
            tasks.append(asyncio.create_task(w.run(stop)))
        tasks.append(asyncio.create_task(loop(stop, wake=wake)))
    yield
    stop.set()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="Folio API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(me.router)
app.include_router(llm.router)
app.include_router(scores.router)
app.include_router(jobs.router)
app.include_router(convert.router)
app.include_router(voice.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
