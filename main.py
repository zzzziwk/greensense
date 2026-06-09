#!/usr/bin/env python3
"""
GreenSense FastAPI 서버
센서 데이터 수신 → WebSocket 브로드캐스트 → AI 진단
"""

import json
import sqlite3
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

import paho.mqtt.client as mqtt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── 전역 상태 ─────────────────────────────────────────────────────
latest_data: dict = {}
connected_ws: list = []

MQTT_BROKER = "localhost"
MQTT_TOPIC  = "greensense/sensor"

# ── SQLite 초기화 ─────────────────────────────────────────────────
def init_db():
    con = sqlite3.connect("greensense.db")
    con.execute("""
        CREATE TABLE IF NOT EXISTS sensor_log (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            ts       TEXT,
            crop     TEXT,
            temp     REAL,
            humi     REAL,
            lux      REAL,
            soil     REAL,
            gas_ppm  REAL,
            alerts   TEXT
        )
    """)
    con.commit()
    con.close()

def save_to_db(d: dict):
    con = sqlite3.connect("greensense.db")
    con.execute(
        "INSERT INTO sensor_log (ts,crop,temp,humi,lux,soil,gas_ppm,alerts) VALUES (?,?,?,?,?,?,?,?)",
        (d.get("timestamp"), d.get("crop"), d.get("temp"), d.get("humi"),
         d.get("lux"), d.get("soil"), d.get("gas_ppm"),
         json.dumps(d.get("alerts", []), ensure_ascii=False))
    )
    con.commit()
    con.close()

# ── WebSocket 브로드캐스트 ────────────────────────────────────────
async def broadcast(data: dict):
    dead = []
    for ws in connected_ws:
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connected_ws.remove(ws)

# ── MQTT 수신 콜백 ────────────────────────────────────────────────
def on_message(client, userdata, msg):
    global latest_data
    try:
        data = json.loads(msg.payload.decode())
        latest_data = data
        save_to_db(data)
        loop = userdata["loop"]
        asyncio.run_coroutine_threadsafe(broadcast(data), loop)
        print(f"[MQTT] 수신: {data}")
    except Exception as e:
        print(f"[MQTT] 오류: {e}")

# ── 앱 라이프사이클 ───────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    loop = asyncio.get_event_loop()

    mq = mqtt.Client(userdata={"loop": loop})
    mq.on_message = on_message
    mq.connect(MQTT_BROKER, 1883, 60)
    mq.subscribe(MQTT_TOPIC)
    mq.loop_start()
    print(f"[MQTT] 브로커 연결 완료 → 토픽: {MQTT_TOPIC}")
    yield
    mq.loop_stop()

# ── FastAPI 앱 ────────────────────────────────────────────────────
app = FastAPI(title="GreenSense API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── REST 엔드포인트 ───────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "message": "GreenSense API 실행 중"}

@app.get("/api/latest")
def get_latest():
    if not latest_data:
        return {"error": "아직 수신된 센서 데이터 없음"}
    return latest_data

@app.get("/api/history")
def get_history(limit: int = 50):
    con = sqlite3.connect("greensense.db")
    rows = con.execute(
        "SELECT ts,crop,temp,humi,lux,soil,gas_ppm,alerts FROM sensor_log ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    con.close()
    keys = ["timestamp","crop","temp","humi","lux","soil","gas_ppm","alerts"]
    return [dict(zip(keys, r)) for r in rows]

# ── AI 진단 엔드포인트 ────────────────────────────────────────────
class DiagnoseRequest(BaseModel):
    crop: Optional[str] = None

@app.post("/api/diagnose")
async def diagnose(req: DiagnoseRequest):
    if not latest_data:
        return {"error": "센서 데이터 없음"}
    data = latest_data.copy()
    if req.crop:
        data["crop"] = req.crop
    try:
        from ai_agent import get_diagnosis
        result = await get_diagnosis(data)
        return {"diagnosis": result}
    except Exception as e:
        return {"error": str(e)}

# ── WebSocket 엔드포인트 ──────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_ws.append(ws)
    print(f"[WS] 클라이언트 연결 (총 {len(connected_ws)}개)")

    if latest_data:
        await ws.send_json(latest_data)

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        connected_ws.remove(ws)
        print(f"[WS] 클라이언트 해제 (총 {len(connected_ws)}개)")

# ── 작물별 수확 예측 파라미터 ─────────────────────────────────────
# 기준온도 출처:
#   상추/시금치: Jenni et al. (1996) J. Amer. Soc. Hort. Sci. / Wurr et al. (1981)
#   깻잎(Perilla): Koike et al. Korean J. Hort. Sci. Technol. / base temp 10°C
#   대파(Welsh onion): Brewster (2008) Onions and Other Vegetable Alliums
#   청경채(Bok choy): Brassica rapa base temp, ScienceDirect 2025 review
# 목표 GDD 출처:
#   상추: Jenni et al. (1996) 실내 재배 기준 450~500 GDD
#   깻잎: 농촌진흥청 재배매뉴얼 + Koike et al. 40일 기준
#   대파: Brewster (2008) 800~900 GDD
#   시금치: Wurr et al. (1981) 400 GDD
#   청경채: Brassica rapa 계열 500 GDD (Tei et al. 1996)

HARVEST_PARAMS = {
    "상추":  {"base_temp": 4,  "target_gdd": 480, "avg_days": 30},
    "깻잎":  {"base_temp": 10, "target_gdd": 560, "avg_days": 40},
    "대파":  {"base_temp": 5,  "target_gdd": 850, "avg_days": 60},
    "시금치": {"base_temp": 4,  "target_gdd": 400, "avg_days": 30},
    "청경채": {"base_temp": 5,  "target_gdd": 490, "avg_days": 35},
}

CROP_STANDARDS_HARVEST = {
    "상추":  {"temp": (15,20), "soil": (65,85), "lux": (8000,11000)},
    "깻잎":  {"temp": (20,25), "soil": (55,65), "lux": (11000,16200)},
    "대파":  {"temp": (15,25), "soil": (60,75), "lux": (5400,11000)},
    "시금치": {"temp": (15,20), "soil": (65,80), "lux": (6500,11000)},
    "청경채": {"temp": (10,25), "soil": (60,75), "lux": (8000,11000)},
}

def calc_correction(row, std):
    """
    FAO-56 수분 스트레스 계수(Ks) 기반 보정
    출처: Allen et al. (1998) FAO Irrigation and Drainage Paper No. 56
    
    수분 스트레스: 토양수분 정상범위 이탈 시 Ks = 0.0~1.0 선형 감소
    조도 보정: Poorter et al. (2012) 광포화점 미달 시 생장률 비례 감소
    온도 보정: GDD 자체가 온도 반영하므로 극값 이탈 시 추가 페널티
    """
    coeff = 1.0
    temp  = row[2]
    soil  = row[5]
    lux   = row[4]

    # 수분 스트레스 Ks (FAO-56 선형 모델)
    # 토양수분 정상범위 하한 미달 → 선형 감소
    if soil is not None:
        soil_lo, soil_hi = std["soil"]
        if soil < soil_lo:
            # Ks = soil / soil_lo (0~1 선형)
            ks = max(0.5, soil / soil_lo)
            coeff *= ks
        elif soil > soil_hi:
            # 과습: 뿌리 산소 부족으로 생장 저하
            coeff *= 0.85

    # 조도 보정 (Poorter et al. 2012)
    # 광포화점 하한 미달 시 비례 감소
    if lux is not None:
        lux_lo, lux_hi = std["lux"]
        if lux < lux_lo:
            light_ratio = max(0.5, lux / lux_lo)
            coeff *= light_ratio

    # 온도 극값 페널티
    # 기준범위 초과 시 GDD 계산과 별도로 생장 억제 반영
    if temp is not None:
        temp_lo, temp_hi = std["temp"]
        if temp > temp_hi + 5:
            coeff *= 0.75  # 고온 장해
        elif temp < temp_lo - 3:
            coeff *= 0.70  # 저온 장해

    return round(coeff, 3)

# ── 작물별 수확 예측 파라미터 ─────────────────────────────────────
HARVEST_PARAMS = {
    "상추":  {"base_temp": 4,  "target_gdd": 480, "avg_days": 30},
    "깻잎":  {"base_temp": 10, "target_gdd": 560, "avg_days": 40},
    "대파":  {"base_temp": 5,  "target_gdd": 850, "avg_days": 60},
    "시금치": {"base_temp": 4,  "target_gdd": 400, "avg_days": 30},
    "청경채": {"base_temp": 5,  "target_gdd": 490, "avg_days": 35},
}

CROP_STANDARDS_HARVEST = {
    "상추":  {"temp": (15,20), "soil": (65,85), "lux": (8000,11000)},
    "깻잎":  {"temp": (20,25), "soil": (55,65), "lux": (11000,16200)},
    "대파":  {"temp": (15,25), "soil": (60,75), "lux": (5400,11000)},
    "시금치": {"temp": (15,20), "soil": (65,80), "lux": (6500,11000)},
    "청경채": {"temp": (10,25), "soil": (60,75), "lux": (8000,11000)},
}

def calc_correction(row, std):
    coeff = 1.0
    temp  = row[2]
    soil  = row[5]
    lux   = row[4]
    if soil is not None:
        soil_lo, soil_hi = std["soil"]
        if soil < soil_lo:
            ks = max(0.5, soil / soil_lo)
            coeff *= ks
        elif soil > soil_hi:
            coeff *= 0.85
    if lux is not None:
        lux_lo, lux_hi = std["lux"]
        if lux < lux_lo:
            light_ratio = max(0.5, lux / lux_lo)
            coeff *= light_ratio
    if temp is not None:
        temp_lo, temp_hi = std["temp"]
        if temp > temp_hi + 5:
            coeff *= 0.75
        elif temp < temp_lo - 3:
            coeff *= 0.70
    return round(coeff, 3)

@app.get("/api/harvest")
def get_harvest(crop: str = "상추", sow_date: str = None):
    if crop not in HARVEST_PARAMS:
        return {"error": f"지원하지 않는 작물: {crop}"}
    params = HARVEST_PARAMS[crop]
    std    = CROP_STANDARDS_HARVEST[crop]
    con  = sqlite3.connect("greensense.db")
    rows = con.execute(
        "SELECT ts, crop, temp, humi, lux, soil, gas_ppm FROM sensor_log ORDER BY id ASC"
    ).fetchall()
    con.close()
    if not rows:
        return {"error": "센서 데이터 없음"}
    from datetime import date, timedelta
    accumulated_gdd = 0.0
    daily_gdd_list  = []
    chunk_size = 288
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i+chunk_size]
        temps = [r[2] for r in chunk if r[2] is not None]
        if not temps:
            continue
        avg_temp = sum(temps) / len(temps)
        gdd_raw  = max(0, avg_temp - params["base_temp"])
        mid_row  = chunk[len(chunk)//2]
        coeff    = calc_correction(mid_row, std)
        gdd_day  = gdd_raw * coeff
        accumulated_gdd += gdd_day
        daily_gdd_list.append(gdd_day)
    recent_gdds   = daily_gdd_list[-7:] if len(daily_gdd_list) >= 7 else daily_gdd_list
    avg_daily_gdd = sum(recent_gdds) / len(recent_gdds) if recent_gdds else 1.0
    target        = params["target_gdd"]
    progress      = min(100.0, round(accumulated_gdd / target * 100, 1))
    remaining_gdd = max(0, target - accumulated_gdd)
    remaining_days = round(remaining_gdd / avg_daily_gdd) if avg_daily_gdd > 0 else params["avg_days"]
    harvest_date  = date.today() + timedelta(days=remaining_days)
    return {
        "crop":            crop,
        "accumulated_gdd": round(accumulated_gdd, 1),
        "target_gdd":      target,
        "progress":        progress,
        "remaining_days":  remaining_days,
        "harvest_date":    str(harvest_date),
        "avg_daily_gdd":   round(avg_daily_gdd, 2),
        "data_points":     len(rows),
    }
