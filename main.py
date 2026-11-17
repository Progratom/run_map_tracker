import asyncio
import csv
import json
import math
import os
import uuid
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

# ==========================================
# GLOBAL CONFIGURATION
# ==========================================
POLL_INTERVAL_SECONDS = 30
#"PASTE_COPIED_COOKIES_HERE"
COOKIES = ""
TRACKS_CSV = "tracks.csv"
RUNNERS_JSON = "runners.json"

PALETTE = [
    "#e63946", "#2a9d8f", "#1d3557", "#f4a261",
    "#8338ec", "#3a86ff", "#ff006e", "#fb5607",
]
CSV_HEADERS = ["track_id", "timestamp", "lat", "lon", "source", "accuracy", "battery"]
# ==========================================

last_seen_ts: dict[str, float] = {}


def init_storage() -> None:
    if not os.path.exists(TRACKS_CSV):
        with open(TRACKS_CSV, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(CSV_HEADERS)
    else:
        with open(TRACKS_CSV, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                tid = row["track_id"]
                ts = float(row["timestamp"])
                if ts > last_seen_ts.get(tid, 0.0):
                    last_seen_ts[tid] = ts

    if not os.path.exists(RUNNERS_JSON):
        with open(RUNNERS_JSON, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2)


def load_runners() -> dict:
    with open(RUNNERS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def save_runners(runners: dict) -> None:
    with open(RUNNERS_JSON, "w", encoding="utf-8") as f:
        json.dump(runners, f, indent=2)


def ensure_runner(track_id: str, default_name: str, source: str) -> None:
    runners = load_runners()
    if track_id not in runners:
        color = PALETTE[len(runners) % len(PALETTE)]
        runners[track_id] = {
            "name": default_name,
            "color": color,
            "source": source,
            "visible": True,
        }
        save_runners(runners)


def append_track_rows(rows: list[dict]) -> None:
    if not rows:
        return
    with open(TRACKS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writerows(rows)


def parse_iso_to_epoch(iso_str: str) -> float:
    return datetime.fromisoformat(iso_str.replace("Z", "+00:00")).timestamp()


async def poll_mapy_loop() -> None:
    headers = {
        "Accept": "application/json",
        "Cookie": COOKIES,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        while True:
            try:
                since = datetime.fromtimestamp(
                    datetime.now(timezone.utc).timestamp() - 300, tz=timezone.utc
                ).isoformat()

                url = "https://mapy.com/api/share-position/subscriptions/me/current"
                resp = await client.get(url, params={"since": since}, headers=headers)

                if resp.status_code in (401, 403):
                    print(f"[Poller] Auth error ({resp.status_code}): Update COOKIES in main.py")
                elif not resp.is_success:
                    print(f"[Poller] HTTP {resp.status_code}: {resp.text[:120]}")
                else:
                    payload = resp.json()
                    items = payload.get("items", [])
                    new_rows = []

                    for item in items:
                        if item.get("sharingStatus") != "active" or not item.get("position"):
                            continue

                        track_id = item.get("deviceId") or item.get("subscriptionId")
                        pos_time_str = item.get("positionTime")
                        if not track_id or not pos_time_str:
                            continue

                        ts = parse_iso_to_epoch(pos_time_str)
                        if ts <= last_seen_ts.get(track_id, 0.0):
                            continue

                        last_seen_ts[track_id] = ts
                        ensure_runner(track_id, item.get("deviceName") or track_id[:8], "live")

                        pos = item["position"]
                        dev_info = item.get("deviceInfo") or {}
                        new_rows.append({
                            "track_id": track_id,
                            "timestamp": ts,
                            "lat": pos["lat"],
                            "lon": pos["lon"],
                            "source": "live",
                            "accuracy": pos.get("accuracy", ""),
                            "battery": dev_info.get("battery", ""),
                        })

                    if new_rows:
                        append_track_rows(new_rows)
                        print(f"[Poller] Saved {len(new_rows)} new point(s).")
                    else:
                        print(f"[Poller] OK ({len(items)} active device(s), no newer GPS timestamp yet).")

            except Exception as exc:
                print(f"[Poller] Network error: {exc}")

            await asyncio.sleep(POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_storage()
    task = asyncio.create_task(poll_mapy_loop())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def parse_gpx(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    points = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag in ("trkpt", "rtept"):
            lat = elem.attrib.get("lat")
            lon = elem.attrib.get("lon")
            if lat is None or lon is None:
                continue
            ts = None
            for child in elem:
                if child.tag.split("}")[-1] == "time" and child.text:
                    try:
                        ts = parse_iso_to_epoch(child.text.strip())
                    except ValueError:
                        ts = None
            points.append({"lat": float(lat), "lon": float(lon), "timestamp": ts})
    return points


@app.get("/")
def serve_ui():
    return FileResponse("index.html")


@app.get("/api/state")
def get_state():
    runners = load_runners()
    tracks: dict[str, list[dict]] = {tid: [] for tid in runners}

    with open(TRACKS_CSV, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tid = row["track_id"]
            if tid not in tracks:
                tracks[tid] = []
            tracks[tid].append({
                "ts": float(row["timestamp"]),
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "source": row["source"],
                "accuracy": float(row["accuracy"]) if row["accuracy"] else None,
                "battery": int(float(row["battery"])) if row["battery"] else None,
            })

    for tid in tracks:
        tracks[tid].sort(key=lambda p: p["ts"])

    return {
        "runners": runners,
        "tracks": tracks,
        "serverTime": datetime.now(timezone.utc).timestamp(),
    }


class RunnerUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    visible: Optional[bool] = None


@app.patch("/api/runners/{track_id}")
def update_runner(track_id: str, update: RunnerUpdate):
    runners = load_runners()
    if track_id not in runners:
        raise HTTPException(status_code=404, detail="Runner not found")

    if update.name is not None:
        runners[track_id]["name"] = update.name.strip() or track_id
    if update.color is not None:
        runners[track_id]["color"] = update.color
    if update.visible is not None:
        runners[track_id]["visible"] = update.visible

    save_runners(runners)
    return runners[track_id]


@app.delete("/api/runners/{track_id}")
def delete_runner(track_id: str):
    runners = load_runners()
    if track_id in runners:
        del runners[track_id]
        save_runners(runners)

    with open(TRACKS_CSV, "r", newline="", encoding="utf-8") as f:
        kept = [r for r in csv.DictReader(f) if r["track_id"] != track_id]

    with open(TRACKS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(kept)

    last_seen_ts.pop(track_id, None)
    return {"deleted": track_id}


@app.post("/api/gpx")
async def upload_gpx(
    file: UploadFile = File(...),
    name: str = Form(""),
    start_time: str = Form(""),
    end_time: str = Form(""),
):
    raw_bytes = await file.read()
    try:
        points = parse_gpx(raw_bytes)
    except ET.ParseError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid GPX XML: {exc}")

    if len(points) < 2:
        raise HTTPException(status_code=400, detail="GPX must contain at least 2 points.")

    has_real_times = all(p["timestamp"] is not None for p in points)
    force_uniform = bool(start_time.strip() and end_time.strip())

    if force_uniform or not has_real_times:
        if not (start_time.strip() and end_time.strip()):
            raise HTTPException(
                status_code=400,
                detail="GPX lacks timestamps. Provide both start_time and end_time.",
            )
        t_start = parse_iso_to_epoch(start_time.strip())
        t_end = parse_iso_to_epoch(end_time.strip())
        if t_end <= t_start:
            raise HTTPException(status_code=400, detail="end_time must be after start_time.")

        cum_dist = [0.0]
        for i in range(1, len(points)):
            d = haversine_meters(
                points[i - 1]["lat"], points[i - 1]["lon"],
                points[i]["lat"], points[i]["lon"],
            )
            cum_dist.append(cum_dist[-1] + d)

        total_dist = cum_dist[-1]
        for i, p in enumerate(points):
            ratio = (cum_dist[i] / total_dist) if total_dist > 0 else (i / (len(points) - 1))
            p["timestamp"] = t_start + ratio * (t_end - t_start)
        source = "gpx_simulated"
    else:
        source = "gpx_real_time"

    track_id = f"gpx_{uuid.uuid4().hex[:8]}"
    track_name = name.strip() or os.path.splitext(file.filename or "GPX Track")[0]
    ensure_runner(track_id, track_name, source)

    rows = [
        {
            "track_id": track_id,
            "timestamp": p["timestamp"],
            "lat": p["lat"],
            "lon": p["lon"],
            "source": source,
            "accuracy": "",
            "battery": "",
        }
        for p in points
    ]
    append_track_rows(rows)
    return {"track_id": track_id, "points": len(rows), "source": source}