"""Access + charging: reserve a port, start, watch live, stop and pay."""
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import config, services
from ..database import get_db
from ..models import ChargingSession, Port, Station, User
from ..schemas import HistoryItem, ReserveIn, SessionOut
from ..security import get_current_user

router = APIRouter(prefix="/api", tags=["access & charging"])

ACTIVE = ("reserved", "charging")


def _owned(db: Session, user: User, session_id: int) -> ChargingSession:
    s = db.get(ChargingSession, session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "Session not found")
    return s


def _active_session(db: Session, user: User) -> Optional[ChargingSession]:
    return db.scalars(
        select(ChargingSession).where(
            ChargingSession.user_id == user.id, ChargingSession.status.in_(ACTIVE)
        )
    ).first()


def _need_balance(user: User) -> None:
    if user.wallet_balance < config.MIN_WALLET_BALANCE:
        raise HTTPException(
            402, f"Add at least ₹{config.MIN_WALLET_BALANCE:.0f} to your wallet before charging"
        )


@router.post("/reservations", response_model=SessionOut, status_code=201)
def reserve(body: ReserveIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    services.release_expired(db)

    existing = _active_session(db, user)
    if existing:
        services.refresh_session(db, existing, user)
        if existing.status in ACTIVE:
            raise HTTPException(409, "You already have an active reservation or charging session")

    station = db.scalar(
        select(Station).where(Station.id == body.station_id)
        .options(selectinload(Station.network), selectinload(Station.ports))
    )
    if station is None:
        raise HTTPException(404, "Charger not found")
    _need_balance(user)

    port = db.scalars(
        select(Port)
        .where(Port.station_id == station.id, Port.status == "available")
        .limit(1)
        .with_for_update()
    ).first()
    if port is None:
        raise HTTPException(409, "No free ports at this charger right now")

    port.status = "reserved"
    s = ChargingSession(
        user_id=user.id,
        station_id=station.id,
        port_id=port.id,
        status="reserved",
        power_kw=min(station.power_kw, config.MAX_VEHICLE_KW),
        price_per_kwh=station.price_per_kwh,
        start_soc=body.start_soc,
        battery_kwh=body.battery_kwh,
        expires_at=services.now() + timedelta(minutes=config.RESERVATION_MINUTES),
    )
    db.add(s)
    db.commit()
    return services.session_out(s, user)


# NOTE: this route must stay above "/sessions/{session_id}", otherwise "active" is read as an id.
@router.get("/sessions/active", response_model=Optional[SessionOut])
def active_session(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = _active_session(db, user)
    if s is None:
        return None
    services.refresh_session(db, s, user)
    return services.session_out(s, user) if s.status in ACTIVE else None


@router.post("/sessions/{session_id}/start", response_model=SessionOut)
def start(session_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = _owned(db, user, session_id)
    services.refresh_session(db, s, user)

    if s.status == "charging":
        return services.session_out(s, user)
    if s.status != "reserved":
        raise HTTPException(409, f"This reservation is {s.status}. Please reserve again.")
    _need_balance(user)

    s.status = "charging"
    s.started_at = services.now()
    s.budget = user.wallet_balance
    s.port.status = "charging"
    db.commit()
    return services.session_out(s, user)


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = _owned(db, user, session_id)
    services.refresh_session(db, s, user)
    return services.session_out(s, user)


@router.post("/sessions/{session_id}/stop", response_model=SessionOut)
def stop(session_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = _owned(db, user, session_id)
    if s.status == "reserved":
        raise HTTPException(409, "Charging has not started. Cancel the reservation instead.")
    if s.status == "charging":
        t = services.now()
        energy, soc, _, reason = services.compute_live(s, t)
        services.settle(db, s, user, energy, soc, reason or "user_stopped", t)
    return services.session_out(s, user)


@router.post("/sessions/{session_id}/cancel", response_model=SessionOut)
def cancel(session_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = _owned(db, user, session_id)
    if s.status != "reserved":
        raise HTTPException(409, "Only a reservation that has not started can be cancelled")
    s.status = "cancelled"
    if s.port.status == "reserved":
        s.port.status = "available"
    db.commit()
    return services.session_out(s, user)


@router.get("/history", response_model=list[HistoryItem])
def history(limit: int = 20, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(ChargingSession)
        .where(ChargingSession.user_id == user.id, ChargingSession.status == "completed")
        .options(selectinload(ChargingSession.station).selectinload(Station.network))
        .order_by(ChargingSession.ended_at.desc())
        .limit(min(max(limit, 1), 100))
    ).all()
    return [
        HistoryItem(
            id=s.id, station_name=s.station.name, network=s.station.network.name,
            date=services.iso(s.ended_at), energy_kwh=round(s.energy_kwh, 1), amount=s.cost,
        )
        for s in rows
    ]