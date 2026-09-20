"""Business logic shared by the routers: distance, scoring, live charging maths, payment."""
import math
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .models import ChargingSession, Port, Station, Transaction, User
from .schemas import SessionOut, StationOut


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def station_out(st: Station, lat: float | None = None, lon: float | None = None) -> StationOut:
    distance = None
    if lat is not None and lon is not None:
        distance = round(haversine_km(lat, lon, st.latitude, st.longitude), 1)
    free = st.available_ports
    return StationOut(
        id=st.id,
        name=st.name,
        network=st.network.name,
        address=st.address,
        latitude=st.latitude,
        longitude=st.longitude,
        power_kw=st.power_kw,
        price_per_kwh=st.price_per_kwh,
        connectors=st.connectors.split(","),
        total_ports=len(st.ports),
        available_ports=free,
        status="available" if free else "busy",
        is_fast=st.power_kw >= config.FAST_CHARGER_KW,
        distance_km=distance,
    )


def match_score(st: Station, distance_km: float) -> float:
    distance = max(0.0, 1 - distance_km / 15)
    speed = min(st.power_kw / 150, 1.0)
    price = min(max(1 - (st.price_per_kwh - 10) / 20, 0.0), 1.0)
    free = st.available_ports / max(len(st.ports), 1)
    return 0.35 * distance + 0.25 * speed + 0.20 * price + 0.20 * free


def release_expired(db: Session) -> None:
    """Free ports whose 15-minute reservation ran out."""
    expired = db.scalars(
        select(ChargingSession).where(
            ChargingSession.status == "reserved", ChargingSession.expires_at <= now()
        )
    ).all()
    for s in expired:
        s.status = "expired"
        port = db.get(Port, s.port_id)
        if port and port.status == "reserved":
            port.status = "available"
    if expired:
        db.commit()


def compute_live(s: ChargingSession, at: datetime) -> tuple[float, float, bool, str | None]:
    """Energy, battery %, finished?, reason - calculated from elapsed time."""
    elapsed = max((at - s.started_at).total_seconds(), 0.0)
    wanted = s.power_kw * elapsed * config.SIM_SPEED / 3600

    room_in_battery = (100 - s.start_soc) / 100 * s.battery_kwh
    room_in_wallet = s.budget / s.price_per_kwh
    limit = min(room_in_battery, room_in_wallet)

    energy = min(wanted, limit)
    soc = min(100.0, s.start_soc + energy / s.battery_kwh * 100)
    finished = wanted >= limit
    reason = None
    if finished:
        reason = "battery_full" if room_in_battery <= room_in_wallet else "wallet_empty"
    return energy, soc, finished, reason


def settle(db: Session, s: ChargingSession, user: User, energy: float, soc: float,
           reason: str, at: datetime) -> None:
    """Finish a session and pay for it from the wallet. Safe to call twice."""
    if s.status != "charging":
        return
    cost = min(round(energy * s.price_per_kwh, 2), user.wallet_balance)
    user.wallet_balance = round(user.wallet_balance - cost, 2)

    s.energy_kwh = round(energy, 3)
    s.cost = cost
    s.end_soc = round(soc, 1)
    s.stop_reason = reason
    s.ended_at = at
    s.status = "completed"

    port = db.get(Port, s.port_id)
    if port:
        port.status = "available"

    db.add(Transaction(
        user_id=user.id,
        session_id=s.id,
        kind="charge",
        amount=-cost,
        balance_after=user.wallet_balance,
        description=f"Charging at {s.station.name} ({s.station.network.name}), {s.energy_kwh:.1f} kWh",
    ))
    db.commit()


def refresh_session(db: Session, s: ChargingSession, user: User) -> None:
    """Expire stale reservations and auto-finish full batteries."""
    t = now()
    if s.status == "reserved" and s.expires_at <= t:
        s.status = "expired"
        port = db.get(Port, s.port_id)
        if port and port.status == "reserved":
            port.status = "available"
        db.commit()
    elif s.status == "charging":
        energy, soc, finished, reason = compute_live(s, t)
        if finished:
            settle(db, s, user, energy, soc, reason or "battery_full", t)


def session_out(s: ChargingSession, user: User) -> SessionOut:
    if s.status == "charging":
        t = now()
        energy, soc, _, _ = compute_live(s, t)
        cost = round(min(energy * s.price_per_kwh, s.budget), 2)
        elapsed = int((t - s.started_at).total_seconds())
    else:
        energy = s.energy_kwh
        soc = s.end_soc if s.end_soc is not None else s.start_soc
        cost = s.cost
        elapsed = int((s.ended_at - s.started_at).total_seconds()) if s.started_at and s.ended_at else 0

    return SessionOut(
        id=s.id,
        status=s.status,
        station_id=s.station_id,
        station_name=s.station.name,
        network=s.station.network.name,
        power_kw=s.power_kw,
        price_per_kwh=s.price_per_kwh,
        start_soc=s.start_soc,
        soc=round(soc, 1),
        energy_kwh=round(energy, 2),
        cost=cost,
        elapsed_seconds=elapsed,
        reserved_until=iso(s.expires_at) if s.status == "reserved" else None,
        started_at=iso(s.started_at),
        ended_at=iso(s.ended_at),
        stop_reason=s.stop_reason,
        wallet_balance=user.wallet_balance,
    )