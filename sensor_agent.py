#!/usr/bin/env python3
"""
GreenSense 센서 통합 수집 에이전트
베란다 실내 재배 환경 기반 논문 기준값
토양수분 센서 2개 (A1, A3) 캘리브레이션 적용
DHT11 최대 3회 재시도
복합 스트레스 2개 이상 시 LED 점등
"""

import time
import adafruit_dht
import board
import spidev
import paho.mqtt.client as mqtt
import json

# ── ADC 설정 ──────────────────────────────────────────────────────
spi = spidev.SpiDev()
spi.open(0, 0)
spi.max_speed_hz = 1350000

def read_adc(channel):
    adc = spi.xfer2([1, (8 + channel) << 4, 0])
    return ((adc[1] & 3) << 8) + adc[2]

# ── 토양수분 캘리브레이션 ─────────────────────────────────────────
SOIL_DRY = 0
SOIL_WET = 750

def adc_to_soil_percent(raw):
    percent = (raw - SOIL_DRY) / (SOIL_WET - SOIL_DRY) * 100
    return round(max(0, min(100, percent)), 1)

def adc_to_lux(raw):
    if raw == 0:
        return 9999
    return round((1023 - raw) / raw * 500, 1)

# ── DHT11 설정 ────────────────────────────────────────────────────
dht = adafruit_dht.DHT11(board.D1)

# ── 작물별 베란다 환경 기반 기준값 ───────────────────────────────
CROP_STANDARDS = {
    "상추": {
        "temp":  (15, 25),
        "humi":  (60, 80),
        "soil":  (50, 85),
        "lux":   (1000, 12500),
        "co2":   (200, 1500),
    },
    "깻잎": {
        "temp":  (15, 24),
        "humi":  (50, 70),
        "soil":  (45, 70),
        "lux":   (2000, 16200),
        "co2":   (200, 1000),
    },
    "대파": {
        "temp":  (15, 25),
        "humi":  (55, 75),
        "soil":  (45, 75),
        "lux":   (800, 11000),
        "co2":   (200, 1000),
    },
    "시금치": {
        "temp":  (10, 20),
        "humi":  (55, 75),
        "soil":  (50, 80),
        "lux":   (1000, 11000),
        "co2":   (200, 1000),
    },
    "청경채": {
        "temp":  (15, 25),
        "humi":  (60, 75),
        "soil":  (45, 75),
        "lux":   (1000, 11000),
        "co2":   (200, 700),
    },
}

# ── 상태 판단 함수 ────────────────────────────────────────────────
def check_status(value, normal_range):
    low, high = normal_range
    if value < low:
        return "낮음"
    elif value > high:
        return "높음"
    else:
        return "정상"

def check_co2(ppm):
    if ppm > 1500:
        return "위험"
    elif ppm > 1000:
        return "주의"
    elif ppm < 200:
        return "낮음"
    else:
        return "정상"

# ── RGB LED 경고 (GPIO D03) ───────────────────────────────────────
from gpiozero import LED
led = LED(3)

def set_alert(is_alert):
    if is_alert:
        led.on()
    else:
        led.off()

# ── 센서 읽기 함수 ────────────────────────────────────────────────
def read_sensors():
    # DHT11 최대 3회 재시도
    temp, humi = None, None
    for _ in range(3):
        try:
            t = dht.temperature
            h = dht.humidity
            if t is not None and h is not None:
                temp, humi = t, h
                break
        except Exception:
            pass
        time.sleep(0.5)

    cds_raw   = read_adc(0)
    soil_raw  = read_adc(1)
    gas_raw   = read_adc(2)
    soil_raw2 = read_adc(3)

    lux       = adc_to_lux(cds_raw)
    soil_pct  = adc_to_soil_percent(soil_raw)
    soil_pct2 = adc_to_soil_percent(soil_raw2)
    soil_avg  = round((soil_pct + soil_pct2) / 2, 1)
    gas_ppm   = gas_raw

    return {
        "temp":     temp,
        "humi":     humi,
        "lux":      lux,
        "soil":     soil_avg,
        "soil1":    soil_pct,
        "soil2":    soil_pct2,
        "gas_raw":  gas_raw,
        "gas_ppm":  gas_ppm,
        "cds_raw":  cds_raw,
        "soil_raw": soil_raw,
    }

# ── 작물별 진단 함수 ──────────────────────────────────────────────
def diagnose(crop_name, sensors):
    if crop_name not in CROP_STANDARDS:
        return {"error": f"지원하지 않는 작물: {crop_name}"}

    std = CROP_STANDARDS[crop_name]
    alerts = []
    result = {"crop": crop_name, "sensors": {}, "alerts": []}

    checks = [
        ("temp", sensors["temp"], "온도(°C)"),
        ("humi", sensors["humi"], "습도(%)"),
        ("soil", sensors["soil"], "토양수분(%)"),
        ("lux",  sensors["lux"],  "조도(lux)"),
    ]

    for key, value, label in checks:
        if value is None:
            status = "측정실패"
        else:
            status = check_status(value, std[key])
        result["sensors"][key] = {"value": value, "status": status, "range": std[key]}
        if status not in ("정상", "측정실패"):
            alerts.append(f"{label} {status} (현재: {value}, 정상범위: {std[key][0]}~{std[key][1]})")

    co2_status = check_co2(sensors["gas_ppm"])
    result["sensors"]["co2"] = {"value": sensors["gas_ppm"], "status": co2_status}
    if co2_status != "정상":
        alerts.append(f"CO₂ {co2_status} (현재: {sensors['gas_ppm']}ppm)")

    result["alerts"] = alerts
    return result

# ── 메인 루프 ─────────────────────────────────────────────────────
def main():
    crop = "상추"
    print(f"GreenSense 센서 모니터링 시작 — 작물: {crop}")
    print("=" * 50)

    mq = mqtt.Client()
    mq.connect("localhost", 1883, 60)

    try:
        while True:
            sensors = read_sensors()
            result  = diagnose(crop, sensors)

            print(f"\n[{time.strftime('%H:%M:%S')}] {crop} 상태 진단")
            print(f"  온도:          {sensors['temp']}°C  → {result['sensors']['temp']['status']}")
            print(f"  습도:          {sensors['humi']}%   → {result['sensors']['humi']['status']}")
            print(f"  조도:          {sensors['lux']} lux → {result['sensors']['lux']['status']}")
            print(f"  토양수분1:     {sensors['soil1']}%")
            print(f"  토양수분2:     {sensors['soil2']}%")
            print(f"  토양수분 평균: {sensors['soil']}%   → {result['sensors']['soil']['status']}")
            print(f"  가스:          {sensors['gas_ppm']} ppm → {result['sensors']['co2']['status']}")

            if result["alerts"]:
                print(f"\n  ⚠️  경고:")
                for alert in result["alerts"]:
                    print(f"     - {alert}")

            if len(result["alerts"]) >= 2:
                set_alert(True)
                print(f"  🔴 LED 점등 (복합 스트레스 {len(result['alerts'])}개)")
            else:
                set_alert(False)
                if not result["alerts"]:
                    print(f"\n  ✅ 모든 항목 정상")
                else:
                    print(f"\n  🟡 경고 1개 (LED 꺼짐)")

            payload = {
                "crop":      crop,
                "timestamp": time.strftime("%H:%M:%S"),
                "temp":      sensors["temp"],
                "humi":      sensors["humi"],
                "lux":       sensors["lux"],
                "soil":      sensors["soil"],
                "soil1":     sensors["soil1"],
                "soil2":     sensors["soil2"],
                "gas_ppm":   sensors["gas_ppm"],
                "alerts":    result["alerts"],
            }
            mq.publish("greensense/sensor", json.dumps(payload, ensure_ascii=False))
            print(f"  [MQTT] 전송 완료")

            time.sleep(5)

    except KeyboardInterrupt:
        print("\n모니터링 종료")
        set_alert(False)
        spi.close()

if __name__ == "__main__":
    main()
