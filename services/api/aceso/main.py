import logging
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from aceso.config import settings
from aceso.db import close_pool, open_pool
from aceso.routes import admin, export, ingest, patients, review

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    yield
    close_pool()


app = FastAPI(title="Aceso API", lifespan=lifespan)


@app.middleware("http")
async def report_crashes(request: Request, call_next):
    """Turn an unexpected failure into a normal JSON error.

    Registered before CORS so the reply still carries the CORS headers: without them
    the browser hides it and the web app can only say "cannot reach the API".
    """
    try:
        return await call_next(request)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        lost_db = isinstance(exc, psycopg.OperationalError)
        return JSONResponse(status_code=503 if lost_db else 500, content={
            "detail": "The database connection was lost. Check the network (WARP) and try again." if lost_db
            else f"The server hit an error: {exc.__class__.__name__}. See the API log."})


app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.web_origin.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (patients, ingest, review, export, admin):
    app.include_router(module.router, prefix="/api")


@app.get("/health")
def health_check():
    return {"status": "ok"}
