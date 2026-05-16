#!/usr/bin/env python3
"""
OpenClaw Replicator — 두 tar 번들 방식
Bundle 1: docker save → openclaw_image.tar (이미지 전체)
Bundle 2: config 파일들 → config_bundle.tar (SOUL/AGENTS/SKILL/destinations)
V2V 전송은 청크 복사로 에뮬레이션
"""
from __future__ import annotations

import json, os, shutil, subprocess, sys, tarfile, tempfile, time
from pathlib import Path

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
    with open(src, "rb") as sf, open(dst, "wb") as df:
        chunk = sf.read(CHUNK_SIZE)
        while chunk:
            df.write(chunk); transferred += len(chunk)
            chunk = sf.read(CHUNK_SIZE)
            pct = transferred / total * 100
            bar = "█" * int(pct/5) + "░" * (20 - int(pct/5))
            print(f"\r  [V2V] {label:22s} [{bar}] {pct:5.1f}%  {transferred/1024/1024:.1f}/{total/1024/1024:.1f} MB", end="", flush=True)
    print(f"\r  [V2V] {label:22s} [{'█'*20}] 100.0%  {total/1024/1024:.1f} MB  {_c('green','✓')}")

def create_image_bundle(output_path):
    output_path = Path(output_path); output_path.parent.mkdir(parents=True, exist_ok=True)
    print(_c("cyan", f"\n[Bundle 1] 이미지 저장 중 → {output_path.name}"))
    t = time.time()
    r = subprocess.run(["docker", "save", OPENCLAW_IMAGE, "-o", str(output_path)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"docker save 실패: {r.stderr}")
    print(f"  완료: {output_path.stat().st_size/1024/1024:.1f} MB  ({time.time()-t:.1f}s)")

def create_config_bundle(output_path, truck1_agent_dir, truck3_template_dir):
    output_path = Path(output_path); output_path.parent.mkdir(parents=True, exist_ok=True)
    truck1_agent_dir = Path(truck1_agent_dir)
    truck3_template_dir = Path(truck3_template_dir)
    print(_c("cyan", f"\n[Bundle 2] Config 번들 생성 중 → {output_path.name}"))
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
                print(f"  [{action:5s}] {rel}")
            else:
                print(f"  [SKIP ] {rel}")
        for rel in IDENTITY_FILES:
            src = truck3_template_dir / rel; dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.exists():
                shutil.copy2(src, dst); print(f"  [id   ] {rel}")
            else:
                print(f"  [SKIP ] {rel}")
        with tarfile.open(output_path, "w:gz") as tar:
            tar.add(tmpdir, arcname=".")
    print(f"  완료: {output_path.stat().st_size/1024:.1f} KB")

class Replicator:
    def __init__(self, truck1_agent_dir=None, truck3_template_dir=None,
                 transfer_dir=None, openclaw_data_dir=None,
                 discord_token="", gateway_token="", openai_api_key=""):
        self.truck1_agent_dir    = Path(truck1_agent_dir    or PROJECT_ROOT/"agents"/"platoon-a")
        self.truck3_template_dir = Path(truck3_template_dir or PROJECT_ROOT/"agents"/"truck3")
        self.transfer_dir        = Path(transfer_dir        or PROJECT_ROOT/".transfer")
        self.openclaw_data_dir   = Path(openclaw_data_dir   or PROJECT_ROOT/".openclaw-truck3")
        self.discord_token       = discord_token  or os.environ.get("TRUCK3_DISCORD_BOT_TOKEN","")
        self.gateway_token       = gateway_token  or os.environ.get("TRUCK3_OPENCLAW_GATEWAY_TOKEN","")
        self.openai_api_key      = openai_api_key or os.environ.get("OPENAI_API_KEY","")

    def replicate(self):
        print(_c("bold", "\n" + "═"*60))
        print(_c("bold", "  OpenClaw 복제 시작 (truck_1 → truck_3)"))
        print("═"*60)

        tx_dir  = self.transfer_dir / "tx"   # truck_1 측 전송 버퍼
        rx_dir  = self.transfer_dir / "rx"   # truck_3 측 수신 버퍼
        image_tar  = tx_dir / "openclaw_image.tar"
        config_tar = tx_dir / "config_bundle.tar"
        rx_image   = rx_dir / "openclaw_image.tar"
        rx_config  = rx_dir / "config_bundle.tar"

        # Bundle 1: 이미지
        create_image_bundle(image_tar)
        print(_c("cyan", "\n[V2V] 이미지 번들 전송 중..."))
        _v2v_transfer(image_tar, rx_image, "openclaw_image.tar")

        # Bundle 2: Config
        create_config_bundle(config_tar, self.truck1_agent_dir, self.truck3_template_dir)
        print(_c("cyan", "\n[V2V] Config 번들 전송 중..."))
        _v2v_transfer(config_tar, rx_config, "config_bundle.tar")

        # vehicle-truck3에서 로드 + 실행
        print(_c("cyan", "\n[vehicle-truck3] 이미지 로드 + config 압축 해제 + openclaw 실행"))
        self._load_and_run(rx_image, rx_config)

        print("\n" + "═"*60)
        print(_c("green", "  복제 완료 ✓"))
        print("═"*60 + "\n")
        return True

    def _load_and_run(self, rx_image, rx_config):
        # docker load
        print("  docker load 중 (이미지)...")
        r = subprocess.run(["docker", "load", "-i", str(rx_image)], capture_output=True, text=True)
        if r.returncode == 0:
            print(f"  {_c('green','이미지 로드 완료')}: {r.stdout.strip()}")
        else:
            print(f"  {_c('yellow','이미지 로드 스킵 (이미 존재)')} {r.stderr[:60]}")

        # config 압축 해제
        self.openclaw_data_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(rx_config, "r:gz") as tar:
            tar.extractall(str(self.openclaw_data_dir))
        print(f"  config 압축 해제 → {self.openclaw_data_dir}")

        # openclaw-truck3 실행 (포트 18792 — truck1의 18789와 충돌 방지)
        subprocess.run(["docker", "rm", "-f", "openclaw-truck3"], capture_output=True)
        cmd = [
            "docker", "run", "-d",
            "--name", "openclaw-truck3",
            "--network", "host",
            "-e", "HOME=/data/openclaw",
            "-e", f"DISCORD_BOT_TOKEN={self.discord_token}",
            "-e", f"OPENCLAW_GATEWAY_TOKEN={self.gateway_token}",
            "-e", f"OPENAI_API_KEY={self.openai_api_key}",
            "-e", "OPENCLAW_GATEWAY_PORT=18792",
            "-v", f"{self.openclaw_data_dir.resolve()}:/data/openclaw",
            "-v", f"{BRIDGE_DIR}:/project/scripts:ro",
            OPENCLAW_IMAGE,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            print(f"  {_c('green','openclaw-truck3 실행됨')} (id={r.stdout.strip()[:12]})")
        else:
            print(f"  {_c('red','openclaw-truck3 실행 실패')}: {r.stderr.strip()}")

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--truck1-agent",    default=str(PROJECT_ROOT/"agents"/"platoon-a"))
    parser.add_argument("--truck3-template", default=str(PROJECT_ROOT/"agents"/"truck3"))
    parser.add_argument("--transfer-dir",    default=str(PROJECT_ROOT/".transfer"))
    parser.add_argument("--openclaw-dir",    default=str(PROJECT_ROOT/".openclaw-truck3"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    r = Replicator(truck1_agent_dir=args.truck1_agent,
                   truck3_template_dir=args.truck3_template,
                   transfer_dir=args.transfer_dir,
                   openclaw_data_dir=args.openclaw_dir)
    if args.dry_run:
        tx = Path(args.transfer_dir) / "tx"
        create_image_bundle(tx / "openclaw_image.tar")
        create_config_bundle(tx / "config_bundle.tar", r.truck1_agent_dir, r.truck3_template_dir)
        print(_c("green", "\ndry-run 완료")); return 0
    return 0 if r.replicate() else 1

if __name__ == "__main__":
    sys.exit(main())
