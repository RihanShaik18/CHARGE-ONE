"""All settings and business rules in one place."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # the FASTAPI folder

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'evcharge.db'}")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-secret-change-me")
TOKEN_HOURS = int(os.getenv("TOKEN_HOURS", "24"))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

RESERVATION_MINUTES = 15
MIN_WALLET_BALANCE = 100.0
SIGNUP_BONUS = 500.0
FAST_CHARGER_KW = 100
MAX_VEHICLE_KW = 120

# 1 real second = SIM_SPEED simulated seconds of charging
SIM_SPEED = float(os.getenv("SIM_SPEED", "12"))

DEFAULT_LAT, DEFAULT_LON = 13.0827, 80.2707