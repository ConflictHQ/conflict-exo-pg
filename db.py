"""Aurora PostgreSQL Serverless v2, scaled to zero.

The interesting property of this fixture is not the data -- it is that the
cluster's minimum capacity is 0 ACU with auto-pause, so between demos the
compute genuinely stops and the only charge is storage.

That makes the first query after an idle period a cold start: Aurora has to
resume before it can answer. This module measures that explicitly, because the
resume is the thing worth showing.
"""

from __future__ import annotations

import os
import time

import psycopg
from psycopg.rows import dict_row

# The postgres binding's env envelope (spec 05 §9.4).
HOST = os.environ.get("POSTGRES_HOST", "")
PORT = os.environ.get("POSTGRES_PORT", "5432")
NAME = os.environ.get("POSTGRES_DB", "postgres")
USER = os.environ.get("POSTGRES_USER", "")
PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")
SSL_MODE = os.environ.get("POSTGRES_SSL_MODE", "require")

# A resume from 0 ACU takes appreciably longer than a warm connect, so the
# timeout has to clear it or the first request after an idle period fails.
CONNECT_TIMEOUT = int(os.environ.get("DB_CONNECT_TIMEOUT", "45"))

_history: list[dict] = []


def configured() -> bool:
    return bool(HOST and USER)


def dsn() -> str:
    return (
        f"host={HOST} port={PORT} dbname={NAME} user={USER} password={PASSWORD} "
        f"sslmode={SSL_MODE} connect_timeout={CONNECT_TIMEOUT}"
    )


def connect():
    """Connect, recording how long it took.

    No pool on purpose: a pooled connection would hide exactly the cold start
    this fixture exists to demonstrate.
    """
    started = time.time()
    conn = psycopg.connect(dsn(), row_factory=dict_row)
    elapsed = round((time.time() - started) * 1000, 1)
    _history.append({
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "connect_ms": elapsed,
        # Anything past a couple of seconds is Aurora resuming rather than a
        # slow network -- a warm connect to a running writer is tens of ms.
        "likely_resume": elapsed > 2000,
    })
    del _history[:-25]
    return conn


def history() -> list[dict]:
    return list(reversed(_history))


def q(sql: str, args=()) -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


SCHEMA = """
CREATE TABLE IF NOT EXISTS planets (
    pl_name TEXT PRIMARY KEY, hostname TEXT, discoverymethod TEXT,
    disc_year INTEGER, disc_facility TEXT, pl_orbper DOUBLE PRECISION,
    pl_rade DOUBLE PRECISION, pl_bmasse DOUBLE PRECISION,
    pl_eqt DOUBLE PRECISION, st_teff DOUBLE PRECISION,
    st_rad DOUBLE PRECISION, st_mass DOUBLE PRECISION,
    sy_dist DOUBLE PRECISION
)
"""

COLUMNS = (
    "pl_name", "hostname", "discoverymethod", "disc_year", "disc_facility",
    "pl_orbper", "pl_rade", "pl_bmasse", "pl_eqt", "st_teff", "st_rad",
    "st_mass", "sy_dist",
)
NUMERIC = {"disc_year", "pl_orbper", "pl_rade", "pl_bmasse", "pl_eqt",
           "st_teff", "st_rad", "st_mass", "sy_dist"}


def seed_if_empty() -> dict:
    """Load the vendored snapshot on first boot.

    Idempotent: a restart against a populated database is a count query, not a
    reload, so a pod cycling does not re-import 6,000 rows.
    """
    import csv

    started = time.time()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(SCHEMA)
        conn.commit()
        cur.execute("SELECT count(*) AS n FROM planets")
        existing = cur.fetchone()["n"]
        if existing:
            return {"seeded": False, "rows": existing,
                    "elapsed_s": round(time.time() - started, 2)}

        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "exoplanets.csv")
        rows = []
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                rows.append(tuple(
                    _num(row.get(c)) if c in NUMERIC else (row.get(c) or "").strip()
                    for c in COLUMNS
                ))
        placeholders = ",".join(["%s"] * len(COLUMNS))
        cur.executemany(
            f"INSERT INTO planets VALUES ({placeholders}) ON CONFLICT DO NOTHING",
            rows,
        )
        conn.commit()
        cur.execute("SELECT count(*) AS n FROM planets")
        return {"seeded": True, "rows": cur.fetchone()["n"],
                "elapsed_s": round(time.time() - started, 2)}


def _num(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None
