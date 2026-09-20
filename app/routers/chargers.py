"""Discovery: one catalogue of chargers from every network."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import config
from ..database import get_db
from ..models import Network, Station
from ..schemas import NetworkOut, RecommendationOut, StationOut, StatsOut
from ..services import haversine_km, match_score, release_expired, station_out

router = APIRouter(prefix="/api", tags=["discovery"])

# words that describe every charger, so they are ignored in searches
GENERIC_WORDS = {"ev", "charging", "charger", "chargers", "station", "stations", "near", "nearby", "by"}


def _all_stations(db: Session) -> list[Station]:
    release_expired(db)
    return db.scalars(
        select(Station).options(selectinload(Station.ports), selectinload(Station.network))
    ).all()


@router.get("/networks", response_model=list[NetworkOut])
def networks(db: Session = Depends(get_db)):
    rows = db.scalars(select(Network).options(selectinload(Network.stations))).all()
    return [NetworkOut(id=n.id, name=n.name, station_count=len(n.stations)) for n in rows]


@router.get("/chargers", response_model=list[StationOut])
def list_chargers(
    lat: float = Query(config.DEFAULT_LAT, ge=-90, le=90),
    lon: float = Query(config.DEFAULT_LON, ge=-180, le=180),
    q: str = "",
    filter: Literal["all", "available", "fast"] = "all",
    network: Optional[str] = None,
    max_price: Optional[float] = Query(None, gt=0),
    sort: Literal["distance", "price", "power"] = "distance",
    db: Session = Depends(get_db),
):
    results = [station_out(s, lat, lon) for s in _all_stations(db)]

    words = [w for w in q.lower().split() if w not in GENERIC_WORDS]
    if words:
        results = [
            r for r in results
            if all(w in f"{r.name} {r.network} {r.address}".lower() for w in words)
        ]
    if filter == "available":
        results = [r for r in results if r.available_ports > 0]
    elif filter == "fast":
        results = [r for r in results if r.is_fast]
    if network:
        results = [r for r in results if r.network.lower() == network.lower()]
    if max_price is not None:
        results = [r for r in results if r.price_per_kwh <= max_price]

    if sort == "price":
        results.sort(key=lambda r: r.price_per_kwh)
    elif sort == "power":
        results.sort(key=lambda r: -r.power_kw)
    else:
        results.sort(key=lambda r: r.distance_km)
    return results


@router.get("/chargers/{station_id}", response_model=StationOut)
def get_charger(
    station_id: int,
    lat: float = Query(config.DEFAULT_LAT),
    lon: float = Query(config.DEFAULT_LON),
    db: Session = Depends(get_db),
):
    release_expired(db)
    st = db.scalar(
        select(Station).where(Station.id == station_id)
        .options(selectinload(Station.ports), selectinload(Station.network))
    )
    if st is None:
        raise HTTPException(404, "Charger not found")
    return station_out(st, lat, lon)


@router.get("/stats", response_model=StatsOut)
def stats(db: Session = Depends(get_db)):
    stations = _all_stations(db)
    if not stations:
        return StatsOut(total_stations=0, available_stations=0, fastest_kw=0, lowest_price=0, networks=0)
    return StatsOut(
        total_stations=len(stations),
        available_stations=sum(1 for s in stations if s.available_ports > 0),
        fastest_kw=max(s.power_kw for s in stations),
        lowest_price=min(s.price_per_kwh for s in stations),
        networks=len({s.network_id for s in stations}),
    )


@router.get("/recommendation", response_model=RecommendationOut)
def recommendation(
    lat: float = Query(config.DEFAULT_LAT),
    lon: float = Query(config.DEFAULT_LON),
    db: Session = Depends(get_db),
):
    """Best charger right now, scored on distance, speed, price and free ports."""
    candidates = [s for s in _all_stations(db) if s.available_ports > 0]
    if not candidates:
        raise HTTPException(404, "No chargers are available right now")

    best, best_score, best_dist = None, -1.0, 0.0
    for s in candidates:
        dist = haversine_km(lat, lon, s.latitude, s.longitude)
        score = match_score(s, dist)
        if score > best_score:
            best, best_score, best_dist = s, score, dist

    return RecommendationOut(
        station=station_out(best, lat, lon),
        match_percent=round(best_score * 100),
        reasons=[
            f"{best_dist:.1f} km away",
            f"{best.power_kw:.0f} kW charging speed",
            f"₹{best.price_per_kwh:.0f} per kWh",
            f"{best.available_ports} of {len(best.ports)} ports free",
        ],
    )
    
