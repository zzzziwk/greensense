#!/usr/bin/env python3
import os
import anthropic

THRESHOLDS = {
    "상추":  {"temp": (15,25), "humi": (60,70), "soil": (65,85), "lux": (8000,11000),  "gas_ppm": (400,1000)},
    "깻잎":  {"temp": (20,25), "humi": (70,80), "soil": (55,65), "lux": (11000,16200), "gas_ppm": (400,1000)},
    "대파":  {"temp": (15,25), "humi": (60,70), "soil": (60,75), "lux": (5400,11000),  "gas_ppm": (400,1000)},
    "시금치": {"temp": (15,20), "humi": (60,70), "soil": (65,80), "lux": (6500,11000),  "gas_ppm": (400,1000)},
    "청경채": {"temp": (10,25), "humi": (70,80), "soil": (60,75), "lux": (8000,11000),  "gas_ppm": (400,1000)},
}

async def get_diagnosis(data: dict) -> str:
    crop = data.get("crop", "상추")
    th   = THRESHOLDS.get(crop, THRESHOLDS["상추"])
    prompt = f"""
당신은 실내 채소 재배 전문가입니다. 아래 센서 데이터를 분석하고 한국어로 진단해주세요.

작물: {crop}

현재 센서값:
- 온도:     {data.get('temp')}°C     (정상범위: {th['temp'][0]}~{th['temp'][1]}°C)
- 습도:     {data.get('humi')}%      (정상범위: {th['humi'][0]}~{th['humi'][1]}%)
- 토양수분: {data.get('soil')}%      (정상범위: {th['soil'][0]}~{th['soil'][1]}%)
- 조도:     {data.get('lux')} lux    (정상범위: {th['lux'][0]}~{th['lux'][1]} lux)
- CO₂:      {data.get('gas_ppm')} ppm (정상범위: {th['gas_ppm'][0]}~{th['gas_ppm'][1]} ppm)
경보 항목:  {data.get('alerts', [])}

아래 형식으로 3문장 이내로 답변해주세요.
마크다운 기호(#, *, **, \\n 등)는 절대 사용하지 마세요.
일반 텍스트로만 작성하세요.
① 현재 상태 요약
② 문제점 (없으면 "이상 없음")
③ 조치 방법 (없으면 "현재 상태 유지")
    """.strip()

    api_key = data.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
    client  = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text
