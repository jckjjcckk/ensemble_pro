from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import llm, me
from .settings import settings

app = FastAPI(title="Folio API", version="0.1.0")

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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
