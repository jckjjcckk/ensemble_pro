import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import jobs, llm, me, scores
from .settings import settings

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The job worker runs inside the API process unless WORKER=0 (e.g. a second process that only serves).
    stop = asyncio.Event()
    task = None
    if os.environ.get("WORKER", "1") != "0" and settings.supabase_url:
        from .worker import loop
        task = asyncio.create_task(loop(stop))
    yield
    stop.set()
    if task:
        await task


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
