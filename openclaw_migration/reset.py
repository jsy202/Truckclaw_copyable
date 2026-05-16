#!/usr/bin/env python3
"""
시나리오 리셋 — 초기 상태로 복귀
- vehicle-truck3, openclaw-truck3 컨테이너 제거
- .openclaw-truck3/, .transfer/ 디렉터리 삭제
- 브리지 서버 상태 초기화 (POST /reload)
- CARLA: 분기된 actor 제거 + 3대 재스폰 (CARLA 있을 때)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.request
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
BRIDGE_URL   = "http://127.0.0.1:18801"

def _c(color, text):
    c = {"green":"\033[32m","yellow":"\033[33m","red":"\033[31m","bold":"\033[1m","reset":"\033[0m"}
    return f"{c.get(color,'')}{text}{c['reset']}"

def stop_container(name: str) -> None:
    r = subprocess.run(["docker", "stop", name], capture_output=True, text=True)
    r2 = subprocess.run(["docker", "rm",   name], capture_output=True, text=True)
    if r.returncode == 0:
        print(f"  {_c('green','✓')} {name} 중지 및 제거")
    else:
        print(f"  - {name} (이미 없음)")

def clean_dirs() -> None:
    for d in [".openclaw-truck3", ".transfer"]:
        path = PROJECT_ROOT / d
        if path.exists():
            shutil.rmtree(path)
            print(f"  {_c('green','✓')} {d}/ 삭제")
        else:
            print(f"  - {d}/ (없음)")

def reset_bridge() -> None:
    try:
        req = urllib.request.Request(
            f"{BRIDGE_URL}/reload",
            data=json.dumps({}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2)
        print(f"  {_c('green','✓')} 브리지 상태 초기화")
    except Exception as e:
        print(f"  {_c('yellow','!')} 브리지 초기화 실패 (서버 꺼져있을 수 있음): {e}")

def reset(carla_coordinator=None) -> None:
    print(_c("bold", "\n── 리셋 시작 ──────────────────────────"))

    print("\n[1] 컨테이너 제거")
    stop_container("openclaw-truck3")
    stop_container("vehicle-truck3")

    print("\n[2] 디렉터리 정리")
    clean_dirs()

    print("\n[3] 브리지 초기화")
    reset_bridge()

    if carla_coordinator is not None:
        print("\n[4] CARLA 재스폰")
        try:
            carla_coordinator.reset()
            print(f"  {_c('green','✓')} CARLA 3대 군집 재스폰 완료")
        except Exception as e:
            print(f"  {_c('red','✗')} CARLA 재스폰 실패: {e}")

    print(_c("bold", "\n── 리셋 완료 — 초기 상태로 복귀 ──────\n"))

if __name__ == "__main__":
    reset()
