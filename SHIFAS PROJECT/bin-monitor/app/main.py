"""FastAPI app: dashboard API + static UI + simple login + on-demand refresh."""
from pathlib import Path

from fastapi import FastAPI, Request, Response, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import URLSafeSerializer, BadSignature

from . import config, queries, live, report_excel, ingest_pilot, process, scheduler, db

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

app = FastAPI(title="AIMS Bin Collection Monitor")
signer = URLSafeSerializer(config.APP_SECRET, salt="session")
COOKIE = "abm_session"


# ---------- auth ----------
def _is_authed(request: Request) -> bool:
    tok = request.cookies.get(COOKIE)
    if not tok:
        return False
    try:
        return signer.loads(tok).get("u") == config.DASHBOARD_USER
    except BadSignature:
        return False


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path
    public = path in ("/login", "/health") or path.startswith("/static")
    if not public and not _is_authed(request):
        if path.startswith("/api"):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return RedirectResponse("/login")
    return await call_next(request)


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return (WEB / "login.html").read_text()


@app.post("/login")
def login(response: Response, username: str = Form(...), password: str = Form(...)):
    if username == config.DASHBOARD_USER and password == config.DASHBOARD_PASS:
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(COOKIE, signer.dumps({"u": username}), httponly=True, samesite="lax")
        return resp
    return RedirectResponse("/login?e=1", status_code=303)


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


# ---------- pages ----------
@app.get("/", response_class=HTMLResponse)
def index():
    return (WEB / "index.html").read_text()


@app.get("/health")
def health():
    return {"ok": True}


# ---------- API ----------
@app.get("/api/bootstrap")
def api_bootstrap():
    return {
        "kpis": queries.kpis(),
        "days": queries.days(),
        "vehicles": queries.vehicles(),
    }


@app.get("/api/map")
def api_map(day: str | None = Query(None), agent: str | None = Query(None)):
    day = day or None
    agent = agent or None
    return {
        "bins": queries.map_bins(day, agent),
        "lifts": queries.map_lifts(day, agent),
        "areas": queries.area_zones(),
        "vehicles": queries.vehicles(),
    }


@app.get("/api/routes")
def api_routes(day: str | None = None, agent: str | None = None):
    return queries.route_lines(day or None, agent or None)


@app.get("/api/track")
def api_track(day: str | None = None, agent: str | None = None):
    return queries.track_lines(day or None, agent or None)


@app.get("/api/points")
def api_points():
    return queries.collection_points()


@app.get("/api/service-check")
def api_service_check():
    return queries.service_checks(only_partial=True)


@app.get("/api/optimized")
def api_optimized():
    return queries.optimized()


@app.get("/api/bins-table")
def api_bins_table():
    return queries.bins_table()


@app.get("/api/violations")
def api_violations(days: int = Query(3, ge=1, le=60)):
    return queries.violations(days)


@app.get("/api/fleet-plan")
def api_fleet_plan(coverage: float = Query(70.0, ge=10, le=100)):
    return queries.fleet_plan(coverage)


@app.get("/api/optimized/route")
def api_optimized_route(n: int, snap: int = 1):
    import json
    from . import optimizer
    row = db.query("SELECT route_no, bins, cbm, km, points FROM optimized_routes WHERE route_no=%s", (n,))
    if not row:
        return {"error": "not found"}
    r = row[0]
    pts = r["points"] if isinstance(r["points"], list) else json.loads(r["points"])
    out = {"route_no": r["route_no"], "bins": r["bins"], "cbm": r["cbm"],
           "straight_km": r["km"], "stops": pts}
    if snap:
        road, road_km = optimizer.snap_to_roads(pts)
        out["points"], out["road_km"] = road, road_km
    else:
        out["points"], out["road_km"] = pts, None
    return out


@app.post("/api/optimize")
def api_optimize(truck_cbm: float = Query(16.0, gt=0), compaction: float = Query(3.5, ge=1),
                 fill: float = Query(0.7, gt=0, le=1), trips_per_day: float = Query(2.5, gt=0)):
    from . import optimizer
    return optimizer.build_optimized_routes(truck_cbm=truck_cbm, compaction=compaction,
                                            fill=fill, trips_per_day=trips_per_day)


@app.get("/api/lifts")
def api_lifts(day: str | None = None, agent: str | None = None, band: str | None = None):
    return queries.lifts(day or None, agent or None, band or None)


@app.get("/api/summary/vehicle-day")
def api_vehicle_day():
    return queries.vehicle_day_summary()


@app.get("/api/summary/area")
def api_area():
    return queries.area_summary()


@app.get("/api/summary/truck-coverage")
def api_truck_coverage():
    return queries.truck_coverage()


@app.post("/api/refresh")
def api_refresh():
    return live.refresh_positions(kind="ondemand")


@app.post("/api/pull")
def api_pull(days: int = Query(7, ge=1, le=30)):
    """On-demand historical pull for the last N days, then re-detect lifts.
    With admin credentials this includes angle/DIS1 (lifts); otherwise position only."""
    res = ingest_pilot.pull_last_days(days)
    if res.get("angle"):
        res["lifts"] = process.process_all()
    return res


@app.on_event("startup")
def _startup():
    scheduler.start()


@app.get("/api/export.xlsx")
def api_export():
    data = report_excel.build_workbook()
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=AIMS_Bin_Collection_Report.xlsx"},
    )


if (WEB / "static").exists():
    app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")
