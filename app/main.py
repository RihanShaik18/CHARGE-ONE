"""EVCharge API.  Run from the FASTAPI folder:   uvicorn app.main:app --reload"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config
from .database import SessionLocal, engine
from .models import Base
from .routers import auth, chargers, sessions, wallet
from .seed import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(
    title="EVCharge API",
    version="1.0.0",
    description="One platform for EV charger discovery, access, charging and payment "
                "across multiple charging networks.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1) the API routes first
app.include_router(auth.router)
app.include_router(chargers.router)
app.include_router(sessions.router)
app.include_router(wallet.router)


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok"}


# 2) the website LAST. FASTAPI\frontend must hold index.html, style.css, script.js.
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    
from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def root():
    return {
        "message": "EV Charging Backend is running"
    }


@app.get("/api/health")
def health():
    return {
        "status": "ok"
    }    