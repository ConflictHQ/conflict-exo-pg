"""conflict-exo-pg — Aurora PostgreSQL Serverless v2 at 0 ACU.

The fixture is not really about exoplanets. It is about a database that costs
nothing while nobody is looking at it: min_acu = 0 with auto-pause means the
compute stops entirely between demos and only storage is billed.

The visible consequence is a cold start, so the dashboard puts connection
latency on the front page rather than hiding it.
"""

import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import db

PORT = int(os.environ.get("PORT", "8080"))
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
BOOT = time.time()
APP = "conflict-exo-pg"
VERSION = os.environ.get("GIT_SHA", "dev")

MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8"}

_seed = {"state": "pending", "detail": None}


def seed_once():
    """Seeding runs off the request path so a cold start plus a 6,000-row
    import cannot hold the readiness probe open."""
    try:
        _seed["detail"] = db.seed_if_empty()
        _seed["state"] = "ready"
    except Exception as exc:
        _seed["state"] = "failed"
        _seed["detail"] = {"error": str(exc)}
    print(json.dumps({"app": APP, "msg": "seed complete", **_seed}), flush=True)


def summary():
    row = db.q(
        "SELECT count(*) AS planets, count(DISTINCT hostname) AS systems, "
        "count(DISTINCT disc_facility) AS facilities, "
        "min(disc_year) AS first_year, max(disc_year) AS last_year FROM planets"
    )[0]
    latest = db.history()
    row["last_connect_ms"] = latest[0]["connect_ms"] if latest else None
    row["engine"] = "Aurora PostgreSQL Serverless v2"
    row["title"] = "Exoplanets on Aurora PostgreSQL"
    row["unit"] = "planets"
    strongest = db.q(
        "SELECT pl_name FROM planets WHERE sy_dist IS NOT NULL ORDER BY sy_dist LIMIT 1"
    )
    row["events"] = row.pop("planets")
    row["significant"] = row.pop("systems")
    row["max_mag"] = None
    row["strongest_place"] = strongest[0]["pl_name"] if strongest else None
    return row


def by_bucket():
    """Discoveries per year -- the same "distribution over an ordinal axis"
    shape the MySQL twin uses for magnitude, so both share one frontend."""
    return db.q(
        "SELECT disc_year AS bucket, count(*) AS n FROM planets "
        "WHERE disc_year IS NOT NULL GROUP BY disc_year ORDER BY disc_year"
    )


def top_rows():
    return db.q(
        "SELECT pl_name AS label, sy_dist AS value, pl_rade AS depth, "
        "CAST(disc_year AS TEXT) AS evt_time FROM planets "
        "WHERE sy_dist IS NOT NULL ORDER BY sy_dist LIMIT 12"
    )


def connections():
    """The cold-start record: what this fixture exists to show."""
    return {"history": db.history(), "seed": _seed}


def debug_payload():
    seen = sorted(k for k in os.environ
                  if not any(s in k.upper() for s in ("SECRET", "PASSWORD", "TOKEN", "KEY")))
    return {
        "app": APP, "version": VERSION, "kind": "deployment",
        "hostname": socket.gethostname(),
        "uptime_s": round(time.time() - BOOT, 1),
        "now": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "env_seen": seen,
        "bindings": {"postgres": "present" if db.configured() else "absent"},
        "seed": _seed,
        "connect_history": db.history()[:5],
    }


def selftest():
    checks = []
    if not db.configured():
        checks.append({"service": "postgres", "ok": False, "latency_ms": None,
                       "detail": None,
                       "error": "POSTGRES_HOST/USER unset -- no postgres bound"})
        return {"app": APP, "ok": False, "checks": checks}

    t0 = time.time()
    try:
        one = db.q("SELECT 1 AS one")[0]["one"]
        latency = round((time.time() - t0) * 1000, 2)
        checks.append({"service": "postgres", "ok": one == 1, "latency_ms": latency,
                       "detail": f"SELECT 1 against {db.HOST}"
                                 + (" (included an Aurora resume)" if latency > 2000 else ""),
                       "error": None})
    except Exception as exc:
        checks.append({"service": "postgres", "ok": False,
                       "latency_ms": round((time.time() - t0) * 1000, 2),
                       "detail": None, "error": str(exc)})

    t0 = time.time()
    try:
        n = db.q("SELECT count(*) AS n FROM planets")[0]["n"]
        checks.append({"service": "dataset", "ok": n > 0,
                       "latency_ms": round((time.time() - t0) * 1000, 2),
                       "detail": f"{n} rows", "error": None})
    except Exception as exc:
        checks.append({"service": "dataset", "ok": False,
                       "latency_ms": round((time.time() - t0) * 1000, 2),
                       "detail": None, "error": str(exc)})

    return {"app": APP, "ok": all(c["ok"] is not False for c in checks), "checks": checks}


ROUTES = {
    "/api/summary": summary, "/api/buckets": by_bucket, "/api/top": top_rows,
    "/api/connections": connections, "/debug": debug_payload, "/selftest": selftest,
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        # Liveness must not touch the database: a paused Aurora would other-
        # wise read as an unhealthy pod and get restarted mid-resume.
        if path == "/health":
            return self._send(200, {"status": "ok", "seed": _seed["state"]})
        if path in ROUTES:
            try:
                return self._send(200, ROUTES[path]())
            except Exception as exc:
                return self._send(503, {"error": str(exc), "hint": "Aurora may be resuming from 0 ACU"})
        if path == "/":
            path = "/index.html"
        target = os.path.normpath(os.path.join(STATIC, path.lstrip("/")))
        if target.startswith(STATIC) and os.path.isfile(target):
            with open(target, "rb") as fh:
                return self._send(200, fh.read(),
                                  MIME.get(os.path.splitext(target)[1], "application/octet-stream"))
        return self._send(404, {"error": "not found", "path": path})

    def log_message(self, fmt, *args):
        print(json.dumps({"app": APP, "msg": fmt % args,
                          "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}), flush=True)


if __name__ == "__main__":
    print(json.dumps({
        "app": APP, "version": VERSION, "port": PORT,
        "bindings": {"postgres": "present" if db.configured() else "absent"},
        "msg": "listening",
    }), flush=True)
    if db.configured():
        threading.Thread(target=seed_once, daemon=True).start()
    else:
        _seed["state"] = "skipped"
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
