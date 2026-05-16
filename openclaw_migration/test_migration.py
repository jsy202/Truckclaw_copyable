#!/usr/bin/env python3
"""
OpenClaw 이동 테스트 — CARLA 없이 실행 가능
터미널에서 실시간으로 두 vehicle의 컨테이너 목록을 보여주면서
OpenClaw 복제 전 과정을 테스트한다.

실행:
  cd /home/jsy/Truckclaw-improve
  python3 openclaw_migration/test_migration.py
  python3 openclaw_migration/test_migration.py --reset  # 완료 후 리셋
"""
from __future__ import annotations

import os, sys, time, threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from openclaw_migration.replicator import Replicator
from openclaw_migration.monitor    import ContainerMonitor
from openclaw_migration.reset      import reset

# .env.single-platoon 로드
env_file = PROJECT_ROOT / ".env.single-platoon"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

TRUCK1_DISCORD = os.environ.get("TRUCK1_DISCORD_BOT_TOKEN", "")
TRUCK1_GATEWAY = os.environ.get("TRUCK1_OPENCLAW_GATEWAY_TOKEN", "")
TRUCK3_DISCORD = os.environ.get("TRUCK3_DISCORD_BOT_TOKEN", "")
TRUCK3_GATEWAY = os.environ.get("TRUCK3_OPENCLAW_GATEWAY_TOKEN", "")
OPENAI_KEY     = os.environ.get("OPENAI_API_KEY", "")


def _c(color, text):
    c = {"green":"\033[32m","yellow":"\033[33m","cyan":"\033[36m",
         "bold":"\033[1m","reset":"\033[0m"}
    return f"{c.get(color,'')}{text}{c['reset']}"


def print_banner():
    print(_c("bold", "\n" + "═"*60))
    print(_c("bold", "  OpenClaw 이동 테스트  (CARLA 없이 실행)"))
    print("═"*60)
    print("  테스트 순서:")
    print("  1. openclaw-truck1 실행 (truck_1 측)")
    print("  2. 터미널 컨테이너 모니터 시작")
    print("  3. 분기 시뮬레이션 (3초 후 자동)")
    print("  4. Bundle 1: 이미지 tar V2V 전송")
    print("  5. Bundle 2: Config tar V2V 전송")
    print("  6. openclaw-truck3 실행 확인")
    print("  Ctrl-C 또는 'r' 입력으로 리셋\n")


def start_truck1_openclaw():
    """truck_1의 openclaw를 호스트에서 직접 실행 (vehicle-truck1 생략 — 테스트용)"""
    import subprocess
    from pathlib import Path

    data_dir = PROJECT_ROOT / ".openclaw-truck1"
    data_dir.mkdir(parents=True, exist_ok=True)

    # agents/platoon-a 복사 (없으면)
    src = PROJECT_ROOT / "agents" / "platoon-a"
    if src.exists() and not (data_dir / "SOUL.md").exists():
        import shutil
        shutil.copytree(src, data_dir, dirs_exist_ok=True)

    subprocess.run(["docker", "rm", "-f", "openclaw-truck1"], capture_output=True)
    cmd = [
        "docker", "run", "-d",
        "--name", "openclaw-truck1",
        "--network", "host",
        "-e", "HOME=/data/openclaw",
        "-e", f"DISCORD_BOT_TOKEN={TRUCK1_DISCORD}",
        "-e", f"OPENCLAW_GATEWAY_TOKEN={TRUCK1_GATEWAY}",
        "-e", f"OPENAI_API_KEY={OPENAI_KEY}",
        "-v", f"{data_dir.resolve()}:/data/openclaw",
        "-v", f"{str(PROJECT_ROOT/'bridge')}:/project/scripts:ro",
        "openclaw:local",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if r.returncode == 0:
        print(f"  {_c('green','✓')} openclaw-truck1 시작됨")
    else:
        print(f"  {_c('yellow','!')} openclaw-truck1: {r.stderr.strip()[:80]}")


def monitor_loop(monitor: ContainerMonitor, stop_event: threading.Event):
    """컨테이너 상태를 계속 출력 (상단 고정 형식)"""
    while not stop_event.is_set():
        lines = monitor.display_lines()
        sys.stdout.write("\033[s")  # 커서 저장
        # 터미널 하단에 컨테이너 상태 표시
        print("\n" + "─"*60)
        for line in lines:
            print(line)
        print("─"*60, flush=True)
        sys.stdout.write("\033[u")  # 커서 복원
        time.sleep(1)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="테스트 후 리셋")
    parser.add_argument("--skip-truck1", action="store_true", help="truck_1 시작 생략")
    args = parser.parse_args()

    print_banner()

    # ── 1. truck_1 openclaw 시작 ──
    if not args.skip_truck1:
        print("[1] openclaw-truck1 시작 중...")
        start_truck1_openclaw()
        time.sleep(3)

    # ── 2. 컨테이너 모니터 시작 ──
    monitor = ContainerMonitor(poll_interval=1.0)
    print("\n[2] 컨테이너 모니터 시작\n")
    time.sleep(1)
    monitor.print_status()

    # ── 3. 분기 대기 ──
    print(f"\n[3] 3초 후 truck_3 분기 시뮬레이션 시작...")
    for i in range(3, 0, -1):
        print(f"    {i}...", end="\r")
        time.sleep(1)

    print(f"\n{'─'*60}")
    print("  목적지 불일치 감지: truck_3 → dest_b  (군집: dest_a)")
    print(f"{'─'*60}\n")

    # ── 4 & 5. 복제 실행 ──
    r = Replicator(
        discord_token=TRUCK3_DISCORD,
        gateway_token=TRUCK3_GATEWAY,
        openai_api_key=OPENAI_KEY,
    )
    r.replicate()

    # ── 6. 결과 확인 ──
    print("\n[6] 최종 컨테이너 상태:")
    time.sleep(3)
    monitor.print_status()

    # ── 리셋 ──
    if args.reset:
        input("\n  Enter를 누르면 리셋합니다...")
        reset()
    else:
        print("\n  리셋하려면: python3 openclaw_migration/test_migration.py --reset")
        print("  또는:      python3 openclaw_migration/reset.py")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n중단됨. 리셋하려면 --reset 옵션으로 다시 실행하세요.")
