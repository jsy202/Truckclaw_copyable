#!/usr/bin/env python3
"""
OpenClaw Replicator  —  openclaw_migration/replicator.py

truck_3이 군집에서 분기될 때 truck_1의 OpenClaw 실행환경을 선택적으로
복사하고 truck_3용 Docker 컨테이너를 새로 실행한다.

Docker-in-Docker 구조 (개념):
  Host
    └── Vehicle Docker (truck_1)
          └── OpenClaw Docker (openclaw-truck1)  ← 소스
    └── Vehicle Docker (truck_3)
          └── OpenClaw Docker (openclaw-truck3)  ← 신규 생성

MVP 에뮬레이션:
  - Vehicle Docker = 호스트의 디렉터리로 대체
  - V2V 전송 = 로컬 파일 청크 복사로 에뮬레이션
  - DinD = 호스트에서 직접 docker run 으로 실행

선택적 복사 전략:
  BEHAVIOR_FILES  : truck_1 agent 템플릿에서 복사 (행동 DNA — 교육/성격)
  IDENTITY_FILES  : truck_3 전용 템플릿으로 대체 (임무지령 — 새 정체성)
  NO_COPY         : 토큰/세션/활성 전송상태 (절대 복사 금지)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
BRIDGE_SCRIPTS_DIR = str(PROJECT_ROOT / "bridge")
OPENCLAW_IMAGE = os.environ.get("OPENCLAW_IMAGE", "openclaw:local")

CHUNK_SIZE = 65_536  # 64 KiB — V2V 청크 단위 에뮬레이션


class Replicator:
    """
    truck_1의 OpenClaw 실행환경을 truck_3으로 복제한다.

    Parameters
    ----------
    truck1_agent_dir : str | Path
        truck_1의 agent 템플릿 디렉터리 (agents/platoon-a/ 또는 agents/truck1/)
    truck3_template_dir : str | Path
        truck_3 전용 agent 템플릿 디렉터리 (agents/truck3/)
    dst_dir : str | Path
        truck_3의 OpenClaw 런타임 데이터 디렉터리 (.openclaw-truck3/)
    container_name : str
        새로 실행할 컨테이너 이름
    port : int
        OpenClaw gateway 포트
    """

    # ── 행동 DNA: truck_1 agent 디렉터리에서 복사 ──────────────────────────────
    # SOUL.md  : patch 적용 (platoon_a → truck3 참조 교체)
    # TOOLS.md : 그대로 복사 (브리지 CLI 명령은 동일)
    # SKILL.md : 그대로 복사 (협상 절차는 보편적)
    BEHAVIOR_FILES: dict[str, str] = {
        "SOUL.md": "patch",
        "TOOLS.md": "copy",
        "skills/platoon-negotiator/SKILL.md": "copy",
    }

    # ── 임무 상태: truck_3 전용 템플릿으로 대체 ────────────────────────────────
    # AGENTS.md                        : bot 이름/Discord ID/platoon_id 완전히 다름
    # data/vehicle_destinations.json  : truck_3의 목적지(dest_b) + 단독 platoon
    # data/platoon_decision_context.json : truck_3 컨텍스트
    IDENTITY_FILES: list[str] = [
        "AGENTS.md",
        "data/vehicle_destinations.json",
        "data/platoon_decision_context.json",
    ]

    def __init__(
        self,
        truck1_agent_dir: str | Path,
        truck3_template_dir: str | Path,
        dst_dir: str | Path,
        container_name: str = "openclaw-truck3",
        port: int = 18792,
    ) -> None:
        self.truck1_agent_dir = Path(truck1_agent_dir)
        self.truck3_template_dir = Path(truck3_template_dir)
        self.dst_dir = Path(dst_dir)
        self.container_name = container_name
        self.port = port

    # ── bundle ─────────────────────────────────────────────────────────────────

    def bundle(self) -> dict[str, bytes]:
        """
        truck_1 agent 디렉터리에서 행동 DNA 파일을 읽어 번들로 묶는다.
        실제 V2V 에서는 이 번들이 무선으로 전송된다고 가정한다.
        """
        bundle: dict[str, bytes] = {}
        print("[replicator] ── bundle phase (truck_1 → bundle) ──────────────")
        for rel, action in self.BEHAVIOR_FILES.items():
            src = self.truck1_agent_dir / rel
            if src.exists():
                bundle[rel] = src.read_bytes()
                print(f"  [bundle] {action:5s}  {rel}  ({len(bundle[rel])} bytes)")
            else:
                print(f"  [bundle] SKIP  {rel}  (파일 없음)")
        return bundle

    # ── V2V 전송 에뮬레이션 ────────────────────────────────────────────────────

    def _v2v_write(self, dst: Path, data: bytes) -> None:
        """청크 단위로 파일 쓰기 (V2V 전송 에뮬레이션)."""
        dst.parent.mkdir(parents=True, exist_ok=True)
        total = len(data)
        transferred = 0
        with open(dst, "wb") as f:
            for offset in range(0, total, CHUNK_SIZE):
                chunk = data[offset : offset + CHUNK_SIZE]
                f.write(chunk)
                transferred += len(chunk)
        print(f"  [v2v] {dst.name}: {transferred}/{total} bytes → {dst}")

    def _v2v_copy(self, src: Path, dst: Path) -> None:
        """파일을 청크 단위로 복사 (V2V 에뮬레이션)."""
        self._v2v_write(dst, src.read_bytes())

    # ── SOUL.md patch ──────────────────────────────────────────────────────────

    def _patch_soul(self, content: str) -> str:
        """
        SOUL.md의 truck_1 정체성 참조를 truck_3으로 교체한다.
        협상 방법/안전 지침 등 행동 로직은 그대로 유지.
        """
        replacements = [
            ("TRUCKCLAW2", "TRUCKCLAW3"),
            ("Platoon A (`platoon_a`)", "Truck 3 (solo vehicle, `platoon_truck3`)"),
            ("platoon_a", "platoon_truck3"),
            ("Platoon A", "Truck 3"),
            ("TRUCKCLAW1", "TRUCKCLAW_PEER"),  # peer 참조 일반화
            # Inbound gate: truck_3의 고유 mention 으로 교체
            ("<@1479297673432399923>", "<@TRUCK3_DISCORD_ID>"),
            ("@TRUCKCLAW2", "@TRUCKCLAW3"),
            # Peer mention
            ("<@1479297098938585170>", "<@PEER_DISCORD_ID>"),
        ]
        for old, new in replacements:
            content = content.replace(old, new)

        # 역할 설명 보정
        content = content.replace(
            "## Role: Initiator",
            "## Role: Solo Navigator (분기 직후 단독 운행)",
        )
        note = (
            "\n\n## Branched Vehicle Note\n\n"
            "You have just branched from Platoon A. Your destination is `dest_b`.\n"
            "You operate independently until you join another platoon heading to `dest_b`.\n"
        )
        content += note
        return content

    # ── restore ────────────────────────────────────────────────────────────────

    def restore(self, bundle: dict[str, bytes]) -> None:
        """
        번들을 truck_3 런타임 디렉터리에 복원한다.
        - 행동 DNA: 번들에서 복원 (SOUL.md는 patch 적용)
        - 정체성 파일: truck_3 전용 템플릿 사용
        """
        print("[replicator] ── restore phase (bundle → truck_3) ─────────────")

        # 행동 DNA 복원
        for rel, action in self.BEHAVIOR_FILES.items():
            data = bundle.get(rel)
            if data is None:
                print(f"  [restore] SKIP  {rel}  (번들에 없음)")
                continue
            dst = self.dst_dir / rel
            if action == "patch" and rel == "SOUL.md":
                patched = self._patch_soul(data.decode("utf-8"))
                self._v2v_write(dst, patched.encode("utf-8"))
            else:
                self._v2v_write(dst, data)

        # 정체성 파일 복원 (truck_3 전용 템플릿)
        print("[replicator]   identity files from truck_3 template:")
        for rel in self.IDENTITY_FILES:
            src = self.truck3_template_dir / rel
            dst = self.dst_dir / rel
            if src.exists():
                self._v2v_copy(src, dst)
            else:
                print(f"  [restore] MISSING template: {rel}")

        print(f"[replicator] 복원 완료: {self.dst_dir}")

    # ── Docker launch ──────────────────────────────────────────────────────────

    def launch_container(self, env_vars: dict[str, str] | None = None) -> bool:
        """
        truck_3용 OpenClaw Docker 컨테이너를 실행한다.
        truck_1의 기존 컨테이너(openclaw-truck1)는 건드리지 않는다.

        DinD 에뮬레이션:
          실제 구조라면 truck_3의 Vehicle Docker 내부에서 실행되어야 하지만,
          MVP에서는 호스트에서 직접 docker run 으로 대체한다.
        """
        print("[replicator] ── launch phase (Docker 컨테이너 시작) ───────────")

        # 기존 컨테이너가 남아있으면 먼저 정리 (이전 실행 잔여물)
        subprocess.run(
            ["docker", "rm", "-f", self.container_name],
            capture_output=True,
        )

        cmd = [
            "docker", "run", "-d",
            "--name", self.container_name,
            "--network", "host",
            "-e", "HOME=/data/openclaw",
            "-v", f"{self.dst_dir.resolve()}:/data/openclaw",
            "-v", f"{BRIDGE_SCRIPTS_DIR}:/project/scripts:ro",
        ]

        # 환경변수 주입 (토큰 등 — 번들로 복사하지 않음)
        for k, v in (env_vars or {}).items():
            cmd += ["-e", f"{k}={v}"]

        cmd.append(OPENCLAW_IMAGE)

        print(f"  [launch] {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                cid = result.stdout.strip()[:12]
                print(f"  [launch] 컨테이너 시작됨: {self.container_name} (id={cid})")
                return True
            else:
                print(f"  [launch] Docker 오류: {result.stderr.strip()}")
                print(f"  [launch] (이미지가 없거나 Docker가 없는 환경에서는 파일 복원만 완료됩니다)")
                return False
        except FileNotFoundError:
            print("  [launch] Docker 명령어를 찾을 수 없음 — 파일 복원만 완료")
            return False
        except Exception as exc:
            print(f"  [launch] 예외 발생: {exc}")
            return False

    # ── main entry ─────────────────────────────────────────────────────────────

    def replicate(self, env_vars: dict[str, str] | None = None) -> bool:
        """
        전체 복제 파이프라인: bundle → restore → launch

        Returns
        -------
        bool : 컨테이너 실행 성공 여부 (파일 복원은 항상 수행됨)
        """
        print("=" * 60)
        print("[replicator] truck_3 OpenClaw 복제 시작")
        print(f"  소스(truck_1 행동DNA) : {self.truck1_agent_dir}")
        print(f"  소스(truck_3 정체성)  : {self.truck3_template_dir}")
        print(f"  목적지(truck_3 런타임): {self.dst_dir}")
        print(f"  컨테이너 이름         : {self.container_name}")
        print("=" * 60)

        bundle = self.bundle()
        self.restore(bundle)
        success = self.launch_container(env_vars)

        status = "완료" if success else "파일복원완료 (컨테이너는 수동 시작 필요)"
        print(f"[replicator] 복제 {status}")
        print("=" * 60)
        return success


# ── CLI ────────────────────────────────────────────────────────────────────────

def _default_replicator() -> Replicator:
    return Replicator(
        truck1_agent_dir=PROJECT_ROOT / "agents" / "platoon-a",
        truck3_template_dir=PROJECT_ROOT / "agents" / "truck3",
        dst_dir=PROJECT_ROOT / ".openclaw-truck3",
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="OpenClaw Replicator — truck_3 복제")
    parser.add_argument("--src-agent", default=str(PROJECT_ROOT / "agents" / "platoon-a"),
                        help="truck_1 agent 템플릿 디렉터리")
    parser.add_argument("--truck3-template", default=str(PROJECT_ROOT / "agents" / "truck3"),
                        help="truck_3 전용 템플릿 디렉터리")
    parser.add_argument("--dst", default=str(PROJECT_ROOT / ".openclaw-truck3"),
                        help="truck_3 런타임 데이터 디렉터리")
    parser.add_argument("--container-name", default="openclaw-truck3")
    parser.add_argument("--port", type=int, default=18792)
    parser.add_argument("--dry-run", action="store_true",
                        help="파일 복원만 수행, Docker 실행 생략")
    parser.add_argument("--truck3-discord-token", default="",
                        help="truck_3 Discord 봇 토큰")
    parser.add_argument("--truck3-gateway-token", default="",
                        help="truck_3 OpenClaw 게이트웨이 토큰")
    args = parser.parse_args()

    r = Replicator(
        truck1_agent_dir=args.src_agent,
        truck3_template_dir=args.truck3_template,
        dst_dir=args.dst,
        container_name=args.container_name,
        port=args.port,
    )

    env_vars = {}
    if args.truck3_discord_token:
        env_vars["DISCORD_BOT_TOKEN"] = args.truck3_discord_token
    if args.truck3_gateway_token:
        env_vars["OPENCLAW_GATEWAY_TOKEN"] = args.truck3_gateway_token

    if args.dry_run:
        bundle = r.bundle()
        r.restore(bundle)
        print("[replicator] dry-run: Docker 실행 생략")
        return 0

    return 0 if r.replicate(env_vars) else 1


if __name__ == "__main__":
    sys.exit(main())
