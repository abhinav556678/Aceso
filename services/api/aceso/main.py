import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aceso.config import settings
from aceso.db import close_pool, open_pool
from aceso.routes import admin, export, ingest, patients, review

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    yield
    close_pool()


app = FastAPI(title="Aceso API", lifespan=lifespan)
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
