#!/usr/bin/env python3
"""
GreenSense AI 진단 모듈 (규칙 기반 더미 버전)
센서값이 기준을 벗어나면 자동으로 진단 문자열 생성
"""

# ── 작물별 기준값 ─────────────────────────────────────────────────
THRESHOLDS = {
    "상추":  {"temp": (15,20), "humi": (60,70), "soil": (65,85), "lux": (8000,11000),  "gas_ppm": (400,1000)},
    "깻잎":  {"temp": (20,25), "humi": (70,80), "soil": (55,65), "lux": (11000,16200), "gas_ppm": (400,1000)},
    "대파":  {"temp": (15,25), "humi": (60,70), "soil": (60,75), "lux": (5400,11000),  "gas_ppm": (400,1000)},
    "시금치": {"temp": (15,20), "humi": (60,70), "soil": (65,80), "lux": (6500,11000),  "gas_ppm": (400,1000)},
    "청경채": {"temp": (10,25), "humi": (70,80), "soil": (60,75), "lux": (8000,11000),  "gas_ppm": (400,1000)},
}

LABELS = {
    "temp":    "온도",
    "humi":    "습도",
    "soil":    "토양수분",
    "lux":     "조도",
    "gas_ppm": "CO₂",
}

UNITS = {
    "temp":    "°C",
    "humi":    "%",
    "soil":    "%",
    "lux":     " lux",
    "gas_ppm": " ppm",
}

# ── 규칙 기반 진단 ────────────────────────────────────────────────
async def get_diagnosis(data: dict) -> str:
    crop = data.get("crop", "상추")
    th   = THRESHOLDS.get(crop, THRESHOLDS["상추"])

    problems = []
    actions  = []

    checks = {
        "temp":    data.get("temp"),
        "humi":    data.get("humi"),
        "soil":    data.get("soil"),
        "lux":     data.get("lux"),
        "gas_ppm": data.get("gas_ppm"),
    }

    for key, value in checks.items():
        if value is None:
            continue
        lo, hi = th[key]
        label  = LABELS[key]
        unit   = UNITS[key]

        if value < lo:
            problems.append(f"{label} 낮음 (현재 {value}{unit}, 기준 {lo}~{hi}{unit})")
            if key == "temp":
                actions.append("난방 또는 보온 조치 필요")
            elif key == "humi":
                actions.append("가습기 사용 또는 분무 권장")
            elif key == "soil":
                actions.append("물주기 필요")
            elif key == "lux":
                actions.append("조명 밝기 높이거나 조사 시간 연장")
            elif key == "gas_ppm":
                actions.append("환기 필요")

        elif value > hi:
            problems.append(f"{label} 높음 (현재 {value}{unit}, 기준 {lo}~{hi}{unit})")
            if key == "temp":
                actions.append("환기 또는 냉방 조치 필요")
            elif key == "humi":
                actions.append("제습 또는 환기 권장")
            elif key == "soil":
                actions.append("물주기 중단, 배수 확인")
            elif key == "lux":
                actions.append("조명 밝기 줄이거나 차광 필요")
            elif key == "gas_ppm":
                actions.append("즉시 환기 필요")

    # ── 진단 문자열 생성 ──────────────────────────────────────────
    if not problems:
        return (
            f"① {crop} 상태가 전반적으로 양호합니다.\n"
            f"② 이상 없음\n"
            f"③ 현재 상태 유지"
        )
    else:
        problem_str = ", ".join(problems)
        action_str  = ", ".join(dict.fromkeys(actions))  # 중복 제거
        return (
            f"① {crop} 재배 환경에 주의가 필요합니다.\n"
            f"② 문제점: {problem_str}\n"
            f"③ 조치 방법: {action_str}"
        )
