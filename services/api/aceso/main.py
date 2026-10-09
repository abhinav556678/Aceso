from fastapi import FastAPI
import threading
from contextlib import asynccontextmanager
from aceso.routes import upload, signoff, search, patient, live, export
from aceso.workers.worker import run_worker_loop

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: connect to db, start background workers
    print("Starting up Aceso API...")
    from aceso.db import pool
    pool.open()
    worker_thread = threading.Thread(target=run_worker_loop, daemon=True)
    worker_thread.start()
    yield
    # Shutdown
    print("Shutting down Aceso API...")
    pool.close()

app = FastAPI(title="Aceso API", lifespan=lifespan)

app.include_router(upload.router, prefix="/api")
app.include_router(signoff.router, prefix="/api/encounters")
app.include_router(search.router, prefix="/api/search")
app.include_router(patient.router, prefix="/api/patients")
app.include_router(live.router, prefix="/api/live")
app.include_router(export.router, prefix="/api/encounters")

@app.get("/health")
def health_check():
    return {"status": "ok"}

