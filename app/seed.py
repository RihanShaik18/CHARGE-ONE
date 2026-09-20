"""Demo data: several networks, several stations. Runs only when the database is empty."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Network, Port, Station

# (network, name, address, lat, lon, power_kw, price, total_ports, free_ports, connectors)
STATIONS = [
    ("GreenCharge",   "GreenCharge Central",       "Central Square",        13.1043, 80.2707, 150, 18, 6, 3, "CCS2,Type2"),
    ("PowerHub",      "EV Power Hub",              "Market Road",           13.0827, 80.3085, 120, 16, 4, 2, "CCS2,CHAdeMO"),
    ("ChargeExpress", "ChargePoint Express",       "Station Road",          13.0665, 80.2707,  60, 14, 4, 0, "CCS2,Type2"),
    ("VoltGrid",      "VoltGrid Mall Stop",        "Mall Complex, West Rd", 13.0827, 80.2412,  50, 12, 4, 4, "CCS2"),
    ("GreenCharge",   "GreenCharge Highway Plaza", "Highway Service Road",  13.1350, 80.2400, 120, 17, 6, 5, "CCS2,Type2"),
    ("PowerHub",      "PowerHub Tech Park",        "IT Corridor",           13.0350, 80.3050,  22, 13, 8, 6, "Type2"),
    ("ChargeExpress", "ChargeExpress Airport Road","Airport Road",          13.0100, 80.2400, 100, 15, 4, 1, "CCS2,CHAdeMO"),
]


def seed(db: Session) -> None:
    if db.scalar(select(func.count(Network.id))):
        return

    networks: dict[str, Network] = {}
    for row in STATIONS:
        name = row[0]
        if name not in networks:
            networks[name] = Network(name=name)
            db.add(networks[name])
    db.flush()

    for network, name, address, lat, lon, power, price, total, free, connectors in STATIONS:
        station = Station(
            network_id=networks[network].id, name=name, address=address,
            latitude=lat, longitude=lon, power_kw=power, price_per_kwh=price,
            connectors=connectors,
        )
        db.add(station)
        db.flush()
        types = connectors.split(",")
        for i in range(total):
            db.add(Port(
                station_id=station.id,
                connector=types[i % len(types)],
                status="available" if i < free else "charging",
            ))
    db.commit()