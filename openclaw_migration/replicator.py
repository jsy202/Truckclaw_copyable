#!/usr/bin/env python3
"""
OpenClaw Replicator — 두 tar 번들 방식
Bundle 1: docker save → openclaw_image.tar (이미지 전체)
Bundle 2: config 파일들 → config_bundle.tar (SOUL/AGENTS/SKILL/destinations)
V2V 전송은 청크 복사로 에뮬레이션
"""
from __future__ import annotations

import json, os, re, shutil, subprocess, sys, tarfile, tempfile, time, threading
from pathlib import Path

# ── thread-local 로그 파일 (replicator 스레드 전용) ─────────────────────────────
# sys.stdout 을 교체하지 않으므로 메인 스레드(시나리오 텔레메트리)와 섞이지 않음
_tlog = threading.local()

def _strip_ansi(text: str) -> str:
    return re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', text)

def _log(msg: str = "", end: str = "\n") -> None:
    """현재 스레드의 log 파일에만 기록 (ANSI 제거)."""
    lf = getattr(_tlog, 'logfile', None)
    if lf:
        try:
            lf.write(_strip_ansi(msg) + end)
            lf.flush()
        except Exception:
            pass

def _print(msg: str = "", end: str = "\n") -> None:
    """watch 스크립트 실행 중: 로그 파일에만 기록 (시나리오 터미널 오염 방지).
    standalone 실행 중(logfile 없음): 현재 터미널에 출력."""
    if getattr(_tlog, 'logfile', None):
        _log(msg, end)
    else:
        print(msg, end=end, flush=True)

PROJECT_ROOT   = Path(__file__).parent.parent
BRIDGE_DIR     = str(PROJECT_ROOT / "bridge")

# .env.single-platoon 자동 로드
def _load_env():
    for name in [".env.single-platoon", ".env"]:
        p = PROJECT_ROOT / name
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())
            break
_load_env()

OPENCLAW_IMAGE = os.environ.get("OPENCLAW_IMAGE", "openclaw:local")
CHUNK_SIZE     = 64 * 1024

def _c(color, text):
    colors = {"reset":"\033[0m","bold":"\033[1m","cyan":"\033[36m",
               "green":"\033[32m","yellow":"\033[33m","red":"\033[31m"}
    return f"{colors.get(color,'')}{text}{colors['reset']}"

# 행동 DNA (truck_1에서 복사)
BEHAVIOR_FILES = {
    "SOUL.md": "patch",
    "TOOLS.md": "copy",
    "skills/platoon-negotiator/SKILL.md": "copy",
}

# 정체성 파일 (truck_3 전용 템플릿으로 대체)
IDENTITY_FILES = [
    "AGENTS.md",
    "data/vehicle_destinations.json",
    "data/platoon_decision_context.json",
]

def _patch_soul(content):
    for old, new in [
        ("TRUCKCLAW2",                    "TRUCKCLAW3"),
        ("Platoon A (`platoon_a`)",        "Truck 3 (solo, `platoon_truck3`)"),
        ("platoon_a",                     "platoon_truck3"),
        ("Platoon A",                     "Truck 3"),
        ("TRUCKCLAW1",                    "TRUCKCLAW_PEER"),
        ("<@1479297673432399923>",         "<@TRUCK3_DISCORD_ID>"),
        ("@TRUCKCLAW2",                   "@TRUCKCLAW3"),
        ("<@1479297098938585170>",         "<@PEER_DISCORD_ID>"),
        ("## Role: Initiator",            "## Role: Solo Navigator (분기 직후 단독 운행)"),
    ]:
        content = content.replace(old, new)
    content += "\n\n## Branched Vehicle Note\nYou have just branched from Platoon A. Your destination is `dest_b`.\n"
    return content

def _v2v_transfer(src, dst, label):
    dst = Path(dst); dst.parent.mkdir(parents=True, exist_ok=True)
    src = Path(src)
    total = src.stat().st_size; transferred = 0
    lf = getattr(_tlog, 'logfile', None)
    with open(src, "rb") as sf, open(dst, "wb") as df:
        chunk = sf.read(CHUNK_SIZE)
        while chunk:
            df.write(chunk); transferred += len(chunk)
            chunk = sf.read(CHUNK_SIZE)
            pct = transferred / total * 100
            bar = "█" * int(pct/5) + "░" * (20 - int(pct/5))
            line = f"\r  [V2V] {label:22s} [{bar}] {pct:5.1f}%  {transferred/1024/1024:.1f}/{total/1024/1024:.1f} MB"
            if lf:
                # watch 모드: \r 애니메이션을 Terminal 1 로그 파일에만 기록
                lf.write(line)
                lf.flush()
            else:
                # standalone 모드: 현재 터미널에 출력
                print(line, end="", flush=True)
    final = f"\r  [V2V] {label:22s} [{'█'*20}] 100.0%  {total/1024/1024:.1f} MB  {_c('green','✓')}\n"
    if lf:
        lf.write(final)
        lf.flush()
    else:
        print(final, end="", flush=True)

def create_image_bundle(output_path):
    output_path = Path(output_path); output_path.parent.mkdir(parents=True, exist_ok=True)
    _print(_c("cyan", f"\n[Bundle 1] 이미지 저장 중 → {output_path.name}"))
    t = time.time()
    r = subprocess.run(["docker", "save", OPENCLAW_IMAGE, "-o", str(output_path)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"docker save 실패: {r.stderr}")
    _print(f"  완료: {output_path.stat().st_size/1024/1024:.1f} MB  ({time.time()-t:.1f}s)")

def create_config_bundle(output_path, truck1_agent_dir, truck3_template_dir):
    output_path = Path(output_path); output_path.parent.mkdir(parents=True, exist_ok=True)
    truck1_agent_dir = Path(truck1_agent_dir)
    truck3_template_dir = Path(truck3_template_dir)
    _print(_c("cyan", f"\n[Bundle 2] Config 번들 생성 중 → {output_path.name}"))
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for rel, action in BEHAVIOR_FILES.items():
            src = truck1_agent_dir / rel; dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.exists():
                content = src.read_text(encoding="utf-8")
                if action == "patch" and "SOUL" in rel:
                    content = _patch_soul(content)
                dst.write_text(content, encoding="utf-8")
                _print(f"  [{action:5s}] {rel}")
            else:
                _print(f"  [SKIP ] {rel}")
        for rel in IDENTITY_FILES:
            src = truck3_template_dir / rel; dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.exists():
                shutil.copy2(src, dst); _print(f"  [id   ] {rel}")
            else:
                _print(f"  [SKIP ] {rel}")
        with tarfile.open(output_path, "w:gz") as tar:
            tar.add(tmpdir, arcname=".")
    _print(f"  완료: {output_path.stat().st_size/1024:.1f} KB")

class BranchReplicator:
    def __init__(self, source_truck_id="truck0", branch_truck_id="truck2",
                 branch_agent_dir=None, source_openclaw_data_dir=None,
                 branch_openclaw_data_dir=None,
                 discord_token="", gateway_token="", openai_api_key=""):
        self.source_truck_id   = source_truck_id
        self.branch_truck_id   = branch_truck_id
        self.source_container  = f"openclaw-{source_truck_id}"
        self.branch_container  = f"openclaw-{branch_truck_id}"

        self.truck1_agent_dir    = Path(PROJECT_ROOT / "agents" / "platoon-a")
        self.truck3_template_dir = branch_agent_dir or (PROJECT_ROOT / "agents" / "truck3")
        self.transfer_dir        = Path(PROJECT_ROOT / ".transfer")
        self.openclaw_data_dir   = branch_openclaw_data_dir or (PROJECT_ROOT / ".openclaw-truck3")
        
        # ⚠️ 사용자 ID 1505107885573673041 에 해당하는 TRUCK3 토큰 사용
        self.discord_token       = discord_token  or os.environ.get("TRUCK3_DISCORD_BOT_TOKEN","")
        self.gateway_token       = gateway_token  or os.environ.get("TRUCK3_OPENCLAW_GATEWAY_TOKEN","")
        self.openai_api_key      = openai_api_key or os.environ.get("OPENAI_API_KEY","")
        
        self._done_event         = threading.Event()
        self._success            = False

    def replicate(self, blocking=True):
        if blocking:
            self._run()
        else:
            t = threading.Thread(target=self._run, daemon=True)
            t.start()
        return True

    def wait(self, timeout=120.0):
        return self._done_event.wait(timeout=timeout)

    def _run(self):
        tx_dir = self.transfer_dir / "tx"
        rx_dir = self.transfer_dir / "rx"
        tx_dir.mkdir(parents=True, exist_ok=True)
        rx_dir.mkdir(parents=True, exist_ok=True)

        tx_log_path = tx_dir / ".progress.log"
        rx_log_path = rx_dir / ".progress.log"

        try:
            image_tar  = tx_dir / "openclaw_image.tar"
            config_tar = tx_dir / "config_bundle.tar"
            rx_image   = rx_dir / "openclaw_image.tar"
            rx_config  = rx_dir / "config_bundle.tar"

            # ── TX 단계 ──────────────────────────────────────────────────────
            # thread-local 로그 파일 설정: 이 스레드의 _print() 만 tx_f 에 기록됨
            # 메인 스레드(시나리오 텔레메트리)는 영향받지 않음
            with open(tx_log_path, "w", buffering=1) as tx_f:
                _tlog.logfile = tx_f
                _log("=== TX START ===")   # watch_truck1 이 감지하는 센티널
                _print(_c("bold", "\n" + "═"*60))
                _print(_c("bold", "  OpenClaw 복제 TX 시작 (truck1 → truck3)"))
                _print("═"*60)

                create_image_bundle(image_tar)
                _print(_c("cyan", "\n[V2V TX] 이미지 번들 전송 중..."))
                _v2v_transfer(image_tar, rx_image, "openclaw_image.tar")

                create_config_bundle(config_tar, self.truck1_agent_dir, self.truck3_template_dir)
                _print(_c("cyan", "\n[V2V TX] Config 번들 전송 중..."))
                _v2v_transfer(config_tar, rx_config, "config_bundle.tar")

                _print(_c("green", "\n[TX 완료] truck3 수신 대기 중...\n"))
                _tlog.logfile = None

            # ── RX 단계 ──────────────────────────────────────────────────────
            with open(rx_log_path, "w", buffering=1) as rx_f:
                _tlog.logfile = rx_f
                _log("=== RX START ===")   # watch_truck3 이 감지하는 센티널
                _print(_c("cyan", "\n[vehicle-truck3] 이미지 로드 + config 압축 해제 + openclaw 실행"))
                self._load_and_run(rx_image, rx_config)
                _tlog.logfile = None

            print("\n" + "═"*60)
            print(_c("green", "  복제 완료 ✓"))
            print("═"*60 + "\n")
            self._success = True
        except Exception as e:
            _tlog.logfile = None
            print(_c("red", f"복제 실패: {e}"))
            self._success = False
        finally:
            _tlog.logfile = None
            self._done_event.set()

    def _load_and_run(self, rx_image, rx_config):
        # docker load
        _print("  docker load 중 (이미지)...")
        r = subprocess.run(["docker", "load", "-i", str(rx_image)], capture_output=True, text=True)
        if r.returncode == 0:
            _print(f"  {_c('green','이미지 로드 완료')}: {r.stdout.strip()}")
        else:
            _print(f"  {_c('yellow','이미지 로드 스킵 (이미 존재)')} {r.stderr[:60]}")

        # config 압축 해제
        self.openclaw_data_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(rx_config, "r:gz") as tar:
            tar.extractall(str(self.openclaw_data_dir))
        _print(f"  config 압축 해제 → {self.openclaw_data_dir}")

        # openclaw-truck3 실행 (포트 18793, --entrypoint 사용)
        subprocess.run(["docker", "rm", "-f", "openclaw-truck3"], capture_output=True)
        _print("  openclaw-truck3 컨테이너 시작 중...")
        cmd = [
            "docker", "run", "-d",
            "--name", "openclaw-truck3",
            "--network", "host",
            "--entrypoint", "/usr/local/bin/openclaw",
            "-e", "HOME=/data/openclaw",
            "-e", f"DISCORD_BOT_TOKEN={self.discord_token}",
            "-e", f"OPENCLAW_GATEWAY_TOKEN={self.gateway_token}",
            "-e", f"OPENAI_API_KEY={self.openai_api_key}",
            "-e", "OPENCLAW_GATEWAY_PORT=18793",
            "-v", f"{self.openclaw_data_dir.resolve()}:/data/openclaw",
            "-v", f"{BRIDGE_DIR}:/project/scripts:ro",
            OPENCLAW_IMAGE,
            "gateway", "run", "--port", "18793", "--allow-unconfigured"
        ]
        subprocess.run(cmd, check=True)
        _print(f"  {_c('green','openclaw-truck3 시작됨 ✓')}")

# ── 구 선두 openclaw 컨테이너 삭제 ───────────────────────────────────────────
def delete_old_openclaw(old_container_name: str):
    """CARLA 분기 완료 후 호출: 구 선두의 openclaw 컨테이너 삭제."""
    print(_c("cyan", f"\n[cleanup] {old_container_name} 컨테이너 삭제 중..."))
    r = subprocess.run(
        ["docker", "rm", "-f", old_container_name],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        print(f"  {_c('green', f'{old_container_name} 삭제 완료')}")
    else:
        print(_c("yellow", f"  {old_container_name} 삭제 실패 (이미 없을 수 있음): {r.stderr.strip()}"))

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--truck1-agent",    default=str(PROJECT_ROOT/"agents"/"platoon-a"))
    parser.add_argument("--truck3-template", default=str(PROJECT_ROOT/"agents"/"truck3"))
    parser.add_argument("--transfer-dir",    default=str(PROJECT_ROOT/".transfer"))
    parser.add_argument("--openclaw-dir",    default=str(PROJECT_ROOT/".openclaw-truck3"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    r = BranchReplicator(source_truck_id="truck1", branch_truck_id="truck3",
                         branch_agent_dir=Path(args.truck3_template),
                         branch_openclaw_data_dir=Path(args.openclaw_dir),
                         discord_token=os.environ.get("TRUCK3_DISCORD_BOT_TOKEN", ""),
                         gateway_token=os.environ.get("TRUCK3_OPENCLAW_GATEWAY_TOKEN", ""))
    if args.dry_run:
        tx = Path(args.transfer_dir) / "tx"
        create_image_bundle(tx / "openclaw_image.tar")
        create_config_bundle(tx / "config_bundle.tar", r.truck1_agent_dir, r.truck3_template_dir)
        print(_c("green", "\ndry-run 완료")); return 0
    return 0 if r.replicate() else 1

if __name__ == "__main__":
    sys.exit(main())
