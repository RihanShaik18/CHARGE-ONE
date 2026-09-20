"""Request and response shapes (what the JSON looks like)."""
from typing import Optional

from pydantic import BaseModel, Field

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(pattern=EMAIL_PATTERN, max_length=120)
    password: str = Field(min_length=6, max_length=100)


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    wallet_balance: float
    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class NetworkOut(BaseModel):
    id: int
    name: str
    station_count: int


class StationOut(BaseModel):
    id: int
    name: str
    network: str
    address: str
    latitude: float
    longitude: float
    power_kw: float
    price_per_kwh: float
    connectors: list[str]
    total_ports: int
    available_ports: int
    status: str
    is_fast: bool
    distance_km: Optional[float] = None


class StatsOut(BaseModel):
    total_stations: int
    available_stations: int
    fastest_kw: float
    lowest_price: float
    networks: int


class RecommendationOut(BaseModel):
    station: StationOut
    match_percent: int
    reasons: list[str]


class ReserveIn(BaseModel):
    station_id: int
    start_soc: float = Field(default=20, ge=0, lt=100)
    battery_kwh: float = Field(default=40, gt=0, le=200)


class SessionOut(BaseModel):
    id: int
    status: str
    station_id: int
    station_name: str
    network: str
    power_kw: float
    price_per_kwh: float
    start_soc: float
    soc: float
    energy_kwh: float
    cost: float
    elapsed_seconds: int
    reserved_until: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    stop_reason: Optional[str] = None
    wallet_balance: float


class HistoryItem(BaseModel):
    id: int
    station_name: str
    network: str
    date: str
    energy_kwh: float
    amount: float


class TopUpIn(BaseModel):
    amount: float = Field(gt=0, le=50000)


class TransactionOut(BaseModel):
    id: int
    kind: str
    amount: float
    balance_after: float
    description: str
    created_at: str


class WalletOut(BaseModel):
    balance: float
    transactions: list[TransactionOut]