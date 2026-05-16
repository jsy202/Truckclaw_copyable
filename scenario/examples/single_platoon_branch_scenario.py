"""
Single-Platoon Branch Scenario
================================
3대 단일 군집 주행 중 truck_3의 목적지가 변경되면 분기하는 시나리오.

차량 구성:
  truck_1 (index 0) : leader, OpenClaw 실행 중 (openclaw-truck1)
  truck_2 (index 1) : follower, OpenClaw 없음
  truck_3 (index 2) : follower → 분기 시 단독 운행 + 새 OpenClaw 실행

분기 흐름:
  CRUISE → GAP_OPEN → DETACH → SPAWN_OC → DONE
  (기존 two_platoon_truck_scenario.py의 splitting/merging 로직 참조)

재사용 컴포넌트:
  - PlatooningSimulator/Core.py       : Platoon, Vehicle, Simulation
  - PlatooningSimulator/PlatooningControllers.py : LeadNavigator, FollowerController
  - config/simulation.json            : 속도/간격 파라미터
  - openclaw_migration/replicator.py  : OpenClaw 복제 및 컨테이너 실행

CARLA 경로: /opt/carla-0.9.6
키 입력:
  '3' : truck_3 분기 수동 트리거
  Ctrl-C : 종료
"""

from __future__ import annotations

import glob
import json
import os
import select
import sys
import termios
import tty
from collections import deque
from enum import Enum, auto

# ── CARLA 경로 설정 ─────────────────────────────────────────────────────────
try:
    sys.path.append(glob.glob(
        '/opt/carla-0.9.6/PythonAPI/carla/dist/carla-*%d.%d-%s.egg' % (
            sys.version_info.major, sys.version_info.minor,
            'win-amd64' if os.name == 'nt' else 'linux-x86_64')
    )[0])
except IndexError:
    pass
sys.path.append('/opt/carla-0.9.6/PythonAPI/carla')

import carla
import numpy as np
from agents.navigation import controller as nav_controller

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from PlatooningSimulator import Core, PlatooningControllers

# ── 설정 로드 ────────────────────────────────────────────────────────────────
CONFIG_FILE = os.path.join(
    os.path.dirname(__file__), '..', '..', 'config', 'simulation.json'
)

def _load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}

_cfg    = _load_config()
_speeds = _cfg.get('speeds', {})
_gaps   = _cfg.get('gaps', {})
_spawns = _cfg.get('spawns', {})

DT              = 0.01
SAMPLING_RATE   = 10
PLATOON_SIZE    = 3

PLATOON_SPACING_M  = float(_gaps.get('platoon_spacing_m', 18.0))
NORMAL_FOLLOW_GAP_M= float(_gaps.get('normal_follow_gap_m', 12.0))
OPEN_GAP_M         = float(_gaps.get('open_gap_m', 20.0))
OPEN_GAP_READY_M   = float(_gaps.get('open_gap_ready_m', 18.0))
SYNC_SPEED_KMH     = float(_speeds.get('sync_speed_kmh', 18.0))

# 자동 분기 트리거 시간 (초). 0 이하면 수동(키보드)만.
BRANCH_AUTO_TRIGGER_S = 30.0

# ── 스폰 위치 (p1_spawn 재사용) ──────────────────────────────────────────────
_s = _spawns.get('p1_spawn', {
    'x': 81.0, 'y': 136.0, 'z': 0.3,
    'pitch': 0.0, 'yaw': 0.2, 'roll': 0.0,
})
PLATOON_SPAWN = carla.Transform(
    carla.Location(x=_s['x'], y=_s['y'], z=_s['z']),
    carla.Rotation(pitch=_s['pitch'], yaw=_s['yaw'], roll=_s['roll']),
)

# ── OpenClaw 복제기 경로 ─────────────────────────────────────────────────────
_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
sys.path.insert(0, _PROJECT_ROOT)

# ── 공통 헬퍼 (기존 two_platoon_truck_scenario.py 에서 재사용) ───────────────

def _yaw_diff(yaw_a: float, yaw_ref: float) -> float:
    return abs((yaw_a - yaw_ref + 180.0) % 360.0 - 180.0)


def _select_straight_waypoint(candidates, yaw_ref):
    if not candidates:
        return None
    return min(candidates, key=lambda w: _yaw_diff(w.transform.rotation.yaw, yaw_ref))


def _retreat_waypoint(wpt, distance_m: float):
    curr = wpt
    rem = float(distance_m)
    while rem > 0.0:
        step = min(10.0, rem)
        nxt = curr.previous(step)
        if not nxt:
            return None
        curr = _select_straight_waypoint(nxt, curr.transform.rotation.yaw)
        rem -= step
    return curr


def _spawn_from_waypoint(wpt):
    t = wpt.transform
    return carla.Transform(
        carla.Location(x=t.location.x, y=t.location.y, z=t.location.z + 0.3),
        t.rotation,
    )


def _set_follow_gap(vehicle, gap_m: float) -> None:
    vehicle.desired_gap_m = float(gap_m)


def v_ref_cacc(pre, ego) -> float:
    """CACC 기반 참조 속도 계산 — 기존 로직 재사용."""
    gap = ego.distance_to(pre)
    vp  = pre.speed
    ve  = ego.speed
    desired_gap = getattr(ego, 'desired_gap_m', NORMAL_FOLLOW_GAP_M)
    gap_err = gap - desired_gap
    v_ref_mps = vp + 0.55 * gap_err + 0.80 * (vp - ve)
    v_ref_kmh = v_ref_mps * 3.6
    return float(np.clip(v_ref_kmh, max(5.0, vp * 3.6 - 14.0), vp * 3.6 + 20.0))


def compute_lead_route(cmap, start_location, distance_m: float = 3000.0, step_m: float = 5.0):
    """리더 차량의 직진 경로 사전 계산 — 기존 로직 재사용."""
    route = deque()
    curr = cmap.get_waypoint(start_location, project_to_road=True,
                             lane_type=carla.LaneType.Driving)
    if curr is None:
        return route
    route.append(curr)
    remaining = float(distance_m)
    while remaining > 0.0:
        nxt = curr.next(min(step_m, remaining))
        if not nxt:
            break
        curr = _select_straight_waypoint(nxt, curr.transform.rotation.yaw)
        route.append(curr)
        remaining -= step_m
    return route


# ── 군집 빌드 ────────────────────────────────────────────────────────────────

def build_single_platoon(
    sim: Core.Simulation,
    blueprint,
    spawn: carla.Transform,
    speed: float,
    tm,
    tm_port: int,
) -> Core.Platoon:
    """3대 단일 군집을 스폰하고 반환한다."""
    p = Core.Platoon(sim)
    lead = p.add_lead_vehicle(blueprint, spawn)
    sim.tick()
    lead.attach_controller(
        PlatooningControllers.LeadNavigator(lead, initial_speed=speed)
    )

    anchor = lead
    awpt = sim.map.get_waypoint(spawn.location)
    for _ in range(PLATOON_SIZE - 1):
        fwpt = _retreat_waypoint(awpt, PLATOON_SPACING_M)
        f_sp = _spawn_from_waypoint(fwpt) if fwpt else anchor.transform_ahead(-PLATOON_SPACING_M)
        f = p.add_follower_vehicle(blueprint, f_sp)
        _set_follow_gap(f, NORMAL_FOLLOW_GAP_M)
        f.attach_controller(
            PlatooningControllers.FollowerController(f, v_ref_cacc, p, dependencies=[-1, 0])
        )
        sim.tick()
        anchor = f
        awpt   = fwpt or awpt

    p.store_follower_waypoints()
    p.lead_waypoints.append(sim.map.get_waypoint(lead.get_location()))
    return p


# ── 상태 머신 ────────────────────────────────────────────────────────────────

class BranchState(Enum):
    CRUISE   = auto()   # 정상 군집 주행
    GAP_OPEN = auto()   # truck_3 후방 간격 확보 중
    DETACH   = auto()   # truck_3 분리
    SPAWN_OC = auto()   # truck_3 OpenClaw 컨테이너 실행
    DONE     = auto()   # 완료 (truck_1+2 계속, truck_3 단독)


class BranchCoordinator:
    """
    3대 단일 군집에서 truck_3(index 2)을 분기시키는 코디네이터.

    분기 트리거: 수동('3' 키) 또는 자동(BRANCH_AUTO_TRIGGER_S 초 경과)
    OpenClaw 복제: Replicator.replicate() 호출
    """

    def __init__(self, platoon: Core.Platoon, tm, tm_port: int) -> None:
        self.platoon    = platoon
        self.tm         = tm
        self.tm_port    = tm_port
        self.state      = BranchState.CRUISE
        self.triggered  = False
        self.branched_v = None   # 분기된 truck_3 Vehicle 인스턴스

    def trigger(self) -> None:
        """분기 트리거 (외부에서 호출)."""
        if self.state == BranchState.CRUISE:
            self.triggered = True

    def update(self, step: int) -> None:
        if self.state == BranchState.CRUISE:
            self._handle_cruise()
        elif self.state == BranchState.GAP_OPEN:
            self._handle_gap_open()
        elif self.state == BranchState.DETACH:
            self._handle_detach()
        elif self.state == BranchState.SPAWN_OC:
            self._handle_spawn_oc()
        # DONE: no-op

    def _handle_cruise(self) -> None:
        if not self.triggered:
            return
        print("[branch] 트리거 확인 → GAP_OPEN 진입")
        print(f"[branch] truck_3 목적지 변경 감지: dest_a → dest_b")
        # truck_3(index 2)의 follow gap을 크게 설정해 후방 간격 확보
        _set_follow_gap(self.platoon[2], OPEN_GAP_M)
        self.state = BranchState.GAP_OPEN

    def _handle_gap_open(self) -> None:
        if len(self.platoon) < 3:
            # 이미 분리된 경우
            self.state = BranchState.DETACH
            return
        gap = self.platoon[1].distance_to(self.platoon[2])
        if gap >= OPEN_GAP_READY_M:
            print(f"[branch] 간격 확보 완료: {gap:.1f}m ≥ {OPEN_GAP_READY_M}m → DETACH")
            self.state = BranchState.DETACH
        else:
            pass  # 다음 tick에 재확인

    def _handle_detach(self) -> None:
        """
        Core.Platoon.split()으로 truck_3을 분리한다.
        분리 후 truck_3은 자신의 LeadNavigator로 계속 주행하거나
        autopilot 으로 전환된다.
        """
        print("[branch] DETACH: truck_3 분리 시작")
        try:
            # split(first=2, last=2) → truck_3만 new_platoon으로 분리
            new_p, _ = self.platoon.split(2, 2)
            self.branched_v = new_p[0]

            # truck_3을 autopilot으로 전환 (독립 주행)
            # TrafficManager가 관리하므로 LeadNavigator 없이도 안전하게 주행
            self.branched_v.set_autopilot(True, self.tm_port)

            print(f"[branch] truck_3 분리 완료 — 독립 운행 시작 (autopilot)")
            print(f"[branch] 남은 군집: truck_1 + truck_2 ({len(self.platoon)}대)")
        except Exception as exc:
            print(f"[branch] DETACH 오류: {exc}")

        self.state = BranchState.SPAWN_OC

    def _handle_spawn_oc(self) -> None:
        """truck_1의 OpenClaw 환경을 truck_3으로 복제하고 컨테이너를 실행한다."""
        print("[branch] SPAWN_OC: OpenClaw 복제 시작")
        try:
            from openclaw_migration.replicator import Replicator

            r = Replicator(
                # truck_1의 행동 DNA 소스: 기존 platoon-a agent 템플릿
                truck1_agent_dir=os.path.join(_PROJECT_ROOT, 'agents', 'platoon-a'),
                # truck_3 전용 정체성 템플릿
                truck3_template_dir=os.path.join(_PROJECT_ROOT, 'agents', 'truck3'),
                # truck_3의 OpenClaw 런타임 데이터 디렉터리
                dst_dir=os.path.join(_PROJECT_ROOT, '.openclaw-truck3'),
                container_name='openclaw-truck3',
                port=18792,
            )

            # 환경변수는 .env 또는 실행 환경에서 주입
            env_vars = {
                k: os.environ[k]
                for k in ('TRUCK3_DISCORD_BOT_TOKEN', 'TRUCK3_OPENCLAW_GATEWAY_TOKEN')
                if k in os.environ
            }

            r.replicate(env_vars or None)

        except ImportError as exc:
            print(f"[branch] replicator import 실패: {exc}")
        except Exception as exc:
            print(f"[branch] OpenClaw 복제 오류: {exc}")

        self.state = BranchState.DONE
        print("[branch] DONE: truck_3 분기 완료")
        print("  - truck_1 + truck_2: 군집 계속 주행")
        print("  - truck_3: 단독 주행 + OpenClaw 실행 (openclaw-truck3)")

    def status_line(self) -> str:
        if self.state == BranchState.GAP_OPEN and len(self.platoon) >= 3:
            gap = self.platoon[1].distance_to(self.platoon[2])
            return f"GAP_OPEN gap={gap:.1f}m / 목표={OPEN_GAP_READY_M}m"
        return self.state.name


# ── 키 입력 (기존 코드 재사용) ───────────────────────────────────────────────

class KeyInput:
    def __init__(self) -> None:
        self._active = False
        try:
            self._fd  = sys.stdin.fileno()
            self._old = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
            self._active = True
            print("[keys] '3' = truck_3 분기 트리거   Ctrl-C = 종료")
        except termios.error:
            print("[keys] TTY 없음 — 키보드 트리거 비활성화 (자동 트리거만 사용)")

    def read(self) -> str:
        if not self._active:
            return ''
        if select.select([sys.stdin], [], [], 0)[0]:
            ch = sys.stdin.read(1)
            if ch == '\x03':
                self.restore()
                raise KeyboardInterrupt
            return ch
        return ''

    def restore(self) -> None:
        if self._active:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
            self._active = False


# ── 카메라 ───────────────────────────────────────────────────────────────────

class SmoothCamera:
    def __init__(self, spectator) -> None:
        self.s = spectator
        self.x = self.y = None

    def update(self, target) -> None:
        loc = target.get_location()
        if self.x is None:
            self.x, self.y = loc.x, loc.y
        self.x += 0.05 * (loc.x - self.x)
        self.y += 0.05 * (loc.y - self.y)
        self.s.set_transform(carla.Transform(
            carla.Location(x=self.x, y=self.y, z=loc.z + 85),
            carla.Rotation(pitch=-90),
        ))


# ── 메인 ─────────────────────────────────────────────────────────────────────

def platoon_gaps(platoon: Core.Platoon) -> str:
    vehicles = list(platoon)
    if len(vehicles) < 2:
        return '-'
    return ', '.join(
        f'{vehicles[i].distance_to(vehicles[i+1]):.1f}m'
        for i in range(len(vehicles) - 1)
    )


def platoon_speeds(platoon: Core.Platoon) -> str:
    return ', '.join(f'{v.speed * 3.6:.1f}' for v in platoon)


def main() -> None:
    sim  = Core.Simulation(world='Town06', dt=DT, synchronous=True)
    cmap = sim.map
    bps  = sim.get_vehicle_blueprints()
    bp   = bps.filter('vehicle.carlamotors.european_hgv')[0]
    tm   = sim.get_trafficmanager()
    tm.set_synchronous_mode(True)
    tm_port = tm.get_port()

    platoon = build_single_platoon(sim, bp, PLATOON_SPAWN, SYNC_SPEED_KMH, tm, tm_port)
    platoon[0].controller.waypoints_ahead = compute_lead_route(
        cmap, platoon[0].get_location()
    )

    coord  = BranchCoordinator(platoon, tm, tm_port)
    kb     = KeyInput()
    camera = SmoothCamera(sim.spectator)
    step   = 0

    print(f"[scenario] 단일 군집 3대 주행 시작")
    print(f"[scenario] truck_1=리더, truck_2=팔로워, truck_3=팔로워(분기 대상)")
    print(f"[scenario] 자동 분기 트리거: {BRANCH_AUTO_TRIGGER_S}초 후")

    try:
        while True:
            elapsed = step * DT

            # 600초 제한
            if elapsed > 600.0:
                print("[scenario] 600초 경과 — 시나리오 종료")
                break

            # 키 입력 처리
            key = kb.read()
            if key == '3':
                print(f"[key] '3' 입력 — truck_3 분기 수동 트리거 (t={elapsed:.1f}s)")
                coord.trigger()

            # 자동 트리거
            if (BRANCH_AUTO_TRIGGER_S > 0
                    and elapsed >= BRANCH_AUTO_TRIGGER_S
                    and coord.state == BranchState.CRUISE):
                print(f"[auto] t={elapsed:.1f}s — truck_3 목적지 변경 감지, 자동 분기 트리거")
                coord.trigger()

            coord.update(step)

            sim.run_step(mode='sample' if step % SAMPLING_RATE == 0 else 'control')
            sim.tick()

            # 카메라: 분기 후에는 truck_1(리더) 추적
            camera_target = (
                platoon[0]._carla_vehicle
                if coord.branched_v is None
                else platoon[0]._carla_vehicle
            )
            camera.update(camera_target)

            # 100 tick 마다 상태 출력
            if step % 100 == 0:
                print(
                    f"t={elapsed:6.1f}s "
                    f"속도=({platoon_speeds(platoon)}) km/h "
                    f"간격=({platoon_gaps(platoon)}) "
                    f"state={coord.status_line()}"
                )

            step += 1

    finally:
        kb.restore()
        sim.release_synchronous()


if __name__ == '__main__':
    main()
