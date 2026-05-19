#!/usr/bin/env python3
"""
Terminal 3 — VEHICLE-TRUCK3 DinD 모니터 (RX side)

상태 전환:
  IDLE     : 시나리오 대기 중
  TELEMETRY: .transfer/telemetry.log 실시간 표시
  RX_ACTIVE: 복제 수신 → .transfer/rx/.progress.log 스트리밍으로 전환
  AUTO_TRIG: openclaw-truck3 부팅 완료 감지 → POST /start_merge 자동 전송

사용법:
  python3 tools/watch_truck3.py
"""
import os, sys, subprocess, time, shutil, urllib.request, json
from pathlib import Path

PROJECT_ROOT  = Path(__file__).resolve().parent.parent
RX_LOG        = PROJECT_ROOT / ".transfer" / "rx" / ".progress.log"
TELEM_LOG     = PROJECT_ROOT / ".transfer" / "telemetry.log"
TRIGGER_URL   = "http://127.0.0.1:18802/start_merge"
BOOT_WAIT_S   = 4.0   # openclaw 게이트웨이 초기화 대기 시간
SCRIPT_START  = time.time()

C = {
    "cyan":   "\033[36m",  "green": "\033[32m",
    "yellow": "\033[33m",  "red":   "\033[31m",
    "bold":   "\033[1m",   "dim":   "\033[2m",
    "reset":  "\033[0m",
}

def c(name, text):
    return f"{C.get(name,'')}{text}{C['reset']}"

STATE_COLORS = {
    "CRUISE":       "cyan",   "GAP":     "yellow",
    "LC":           "yellow", "MIGRATE": "yellow",
    "SIDE_BY_SIDE": "green",  "DONE":    "green",
    "IDLE":         "dim",
}

def colorize(line):
    for st, col in STATE_COLORS.items():
        tag = f"state={st}"
        if tag in line:
            line = line.replace(tag, c(col, tag))
            break
    return line

def container_status(name):
    try:
        r = subprocess.run(
            ["docker", "ps", "--all", "--filter", f"name=^/{name}$",
             "--format", "{{.Status}}"],
            capture_output=True, text=True, timeout=2)
        s = r.stdout.strip()
        return s if s else "없음"
    except Exception:
        return "docker 응답 없음"

def post_merge_trigger():
    """POST /start_merge → CARLA 분기 트리거."""
    try:
        req = urllib.request.Request(
            TRIGGER_URL,
            data=json.dumps({}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3)
        return True
    except Exception as e:
        return False

def draw_header():
    w = min(shutil.get_terminal_size((80, 24)).columns, 72)
    ln = "─" * (w - 2)
    print(c("bold", f"┌{ln}┐"))
    print(c("bold", "│") +
          f"  VEHICLE-TRUCK3  [{c('red','분기 대상')} {c('bold','│')} {c('cyan','DinD 모니터')}]")
    print(c("bold", f"└{ln}┘"))
    print()

def draw_inner_status():
    st = container_status("openclaw-truck3")
    if "Up" in st:
        dot = c("green", "●")
        print(f"  {dot}  inner docker : {c('bold','openclaw-truck3')}  {c('dim', st)}")
    else:
        print(f"  {c('dim','○')}  inner docker : {c('dim','없음  (복제 대기 중)')}")
    print()

def draw_telem_header():
    w = min(shutil.get_terminal_size((80, 24)).columns, 72)
    print(c("bold", "─" * (w - 2)))
    print(f"  {c('cyan','[텔레메트리]')}  CARLA 시뮬레이션 제어값  (100 틱마다 갱신)")
    print(c("bold", "─" * (w - 2)))
    print()

def tail_new(path, pos):
    try:
        sz = path.stat().st_size
        if sz < pos:
            pos = 0
        if sz > pos:
            with open(path, errors="replace") as f:
                f.seek(pos)
                return f.read(), sz
    except Exception:
        pass
    return "", pos

def main():
    os.system("clear")
    print()
    draw_header()
    print(f"  {c('yellow','[RX]')} 시나리오 시작 대기 중...")

    state          = "idle"
    telem_pos      = 0
    rx_pos         = 0
    last_idle      = time.time()
    container_up_ts = None   # openclaw-truck3 Up 감지 시각
    branch_sent    = False

    while True:
        # ── RX 로그에서 센티널(=== RX START ===) 감지 → RX 모드 전환 ────────
        if state not in ("rx", "done") and RX_LOG.exists():
            try:
                if (RX_LOG.stat().st_mtime > SCRIPT_START and
                        "=== RX START ===" in RX_LOG.read_text(errors="replace")):
                    os.system("clear")
                    print()
                    draw_header()
                    print(f"  {c('dim','○')}  inner docker : {c('dim','수신 중...')}")
                    print()
                    print(c("bold", "═" * 62))
                    print(c("bold", "  OpenClaw 복제 RX 시작  (truck1 ──▶ truck3)"))
                    print(c("bold", "═" * 62))
                    print()
                    state  = "rx"
                    rx_pos = 0
            except Exception:
                pass

        if state == "rx":
            chunk, rx_pos = tail_new(RX_LOG, rx_pos)
            if chunk:
                # 센티널 라인만 제거하고 나머지는 raw 출력
                output = chunk.replace("=== RX START ===\n", "").replace("=== RX START ===", "")
                if output:
                    sys.stdout.write(output)
                    sys.stdout.flush()

            # openclaw-truck3 부팅 완료 감지
            if container_up_ts is None:
                st = container_status("openclaw-truck3")
                if "Up" in st:
                    container_up_ts = time.time()
                    print()
                    print(c("bold", "─" * 62))
                    print(f"  {c('green','●')}  openclaw-truck3  {c('dim', st)}")
                    print(f"  {c('yellow','[AUTO]')} {BOOT_WAIT_S:.0f}초 후 분기 트리거 자동 전송...")
                    print(c("bold", "─" * 62))

            # 대기 후 트리거 전송
            if container_up_ts and not branch_sent:
                if time.time() - container_up_ts >= BOOT_WAIT_S:
                    ok = post_merge_trigger()
                    if ok:
                        print()
                        print(c("bold", "═" * 62))
                        print(c("green", f"  [AUTO] POST {TRIGGER_URL}"))
                        print(c("green", "  분기 트리거 전송 완료 → CARLA 군집 이탈 시작"))
                        print(c("bold", "═" * 62))
                    else:
                        print(c("red", f"  [AUTO] 트리거 전송 실패 ({TRIGGER_URL})"))
                    branch_sent = True
                    state = "done"

        elif state == "idle":
            if (TELEM_LOG.exists() and TELEM_LOG.stat().st_size > 0 and
                    TELEM_LOG.stat().st_mtime > SCRIPT_START):
                os.system("clear")
                print()
                draw_header()
                draw_inner_status()
                draw_telem_header()
                state = "telem"
            elif time.time() - last_idle > 5:
                os.system("clear")
                print()
                draw_header()
                print(f"  {c('yellow','[RX]')} 시나리오 시작 대기 중...")
                last_idle = time.time()

        elif state == "telem":
            chunk, telem_pos = tail_new(TELEM_LOG, telem_pos)
            if chunk:
                for line in chunk.splitlines():
                    if line.strip():
                        print("  " + colorize(line))

        # done 상태: 이미 트리거 전송 완료, 주기적으로 컨테이너 상태만 표시
        # (아무것도 더 할 일 없음)

        time.sleep(0.05)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[watch_truck3] 종료")
