#!/usr/bin/env python3
from gpiozero import OutputDevice
import time

# SPI 핀(7,8,9,10,11) 피해서 설정
IN1A = OutputDevice(17)
IN1B = OutputDevice(27)
IN2A = OutputDevice(22)
IN2B = OutputDevice(23)

# ULN2003 4상 스텝 시퀀스
STEP_SEQ = [
    [1,0,0,0],
    [1,1,0,0],
    [0,1,0,0],
    [0,1,1,0],
    [0,0,1,0],
    [0,0,1,1],
    [0,0,0,1],
    [1,0,0,1],
]

def set_step(a1, b1, a2, b2):
    IN1A.value = a1
    IN1B.value = b1
    IN2A.value = a2
    IN2B.value = b2

def motor_open(steps=512, delay=0.002):
    print("문 열기...")
    for _ in range(steps):
        for seq in STEP_SEQ:
            set_step(*seq)
            time.sleep(delay)
    set_step(0,0,0,0)
    print("완료")

def motor_close(steps=512, delay=0.002):
    print("문 닫기...")
    for _ in range(steps):
        for seq in reversed(STEP_SEQ):
            set_step(*seq)
            time.sleep(delay)
    set_step(0,0,0,0)
    print("완료")

if __name__ == "__main__":
    try:
        motor_open()
        time.sleep(1)
        motor_close()
    except KeyboardInterrupt:
        set_step(0,0,0,0)
        print("\n종료")
