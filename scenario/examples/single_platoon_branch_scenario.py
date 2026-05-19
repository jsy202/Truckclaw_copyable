#!/usr/bin/env python3
"""
Single-Platoon Branch Scenario — CARLA 0.9.13 + OpenClaw 분기
=============================================================
improve(two_platoon_truck_scenario.py) 로직 베이스.
vehicle: vehicle.carlamotors.european_hgv
spawn:   simulation.json p1_spawn (x=81, y=136)

군집: truck0(선두) → truck1 → truck2(후미)  3대

분기 흐름:
  1. 키보드 '3' 또는 HTTP POST :18802/start_merge
  2. OpenClaw 세션 복제 시작 (백그라운드): truck0 → truck2
  3. CARLA: truck2 갭 확보 → 옆 차선 이동 → 분리
  4. 분리 완료 → 브리지 /branch complete 호출
  5. truck2 openclaw 컨테이너 삭제

포트:
  18801 — 브리지 서버
  18802 — 분기 트리거
"""
from __future__ import annotations

import glob, json, math, os, select, sys, termios, threading, tty
import urllib.error, urllib.request, time
from collections import deque
from enum import Enum, auto
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# ── CARLA 경로 (자동 감지 또는 시스템 설치 선호) ──────────────────────────────
# CARLA_EGG = "/opt/carla-0.9.6/PythonAPI/carla/dist/carla-0.9.6-py3.5-linux-x86_64.egg"
# CARLA_API = "/opt/carla-0.9.6/PythonAPI/carla"
# for p in (CARLA_EGG, CARLA_API):
#     if p not in sys.path: sys.path.insert(0, p)

import carla
import numpy as np
from agents.navigation import controller as nav_controller

_PROJECT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT / "scenario" / "src"))
sys.path.insert(0, str(_PROJECT / "openclaw_migration"))
from PlatooningSimulator import Core, PlatooningControllers

# ── config (improve simulation.json 그대로) ──────────────────────────────────
_CFG  = json.loads((_PROJECT / "config" / "simulation.json").read_text())
_spd  = _CFG["speeds"]; _gap = _CFG["gaps"]; _sp = _CFG["spawns"]

DT                  = 0.01
SAMPLING_RATE       = 10
PLATOON_SIZE        = 3
SYNC_SPEED_KMH      = 20.0
MERGE_MIN_SPEED_KMH = 15.0
NORMAL_FOLLOW_GAP_M = 15.0                                   # ⚠️ 고속 대응
OPEN_GAP_M          = 20.0
OPEN_GAP_READY_M    = 15.0                                   # ⚠️ 단축
TARGET_GAP_M        = 13.0
PLATOON_SPACING_M   = 20.0
LANE_STEP_COMPLETE_M = 0.9
GAP_STABLE_TICKS    = 10                                     # ⚠️ 빠른 전환

BRIDGE_URL   = "http://127.0.0.1:18801"
TRIGGER_PORT = 18802

# ── 스폰 (improve p1_spawn 그대로) ──────────────────────────────────────────
_p1 = _sp["p1_spawn"]
PLATOON_SPAWN = carla.Transform(
    carla.Location(x=_p1["x"], y=_p1["y"], z=_p1["z"]),
    carla.Rotation(pitch=_p1["pitch"], yaw=_p1["yaw"], roll=_p1["roll"]),
)

# ── 이벤트 ────────────────────────────────────────────────────────────────────
_branch_trigger_event  = threading.Event()
_branch_complete_event = threading.Event()
_replicate_only_event  = threading.Event()  # 복제만 시작 (분기는 truck3 부팅 후 자동)

# ── improve 헬퍼 함수 그대로 ──────────────────────────────────────────────────
def _yaw_diff(a, ref):
    return abs((a - ref + 180.0) % 360.0 - 180.0)

def _select_straight(cands, yaw):
    return min(cands, key=lambda w: _yaw_diff(w.transform.rotation.yaw, yaw)) if cands else None

def _advance_waypoint(wpt, dist):
    cur = wpt; rem = float(dist)
    while rem > 0.0:
        step = min(10.0, rem)
        nxt = cur.next(step)
        if not nxt: return cur
        cur = _select_straight(nxt, cur.transform.rotation.yaw)
        rem -= step
    return cur

def _retreat_waypoint(wpt, dist):
    cur = wpt; rem = float(dist)
    while rem > 0.0:
        step = min(10.0, rem)
        nxt = cur.previous(step)
        if not nxt: return None
        cur = _select_straight(nxt, cur.transform.rotation.yaw)
        rem -= step
    return cur

def _spawn_from_waypoint(wpt):
    t = wpt.transform
    return carla.Transform(
        carla.Location(x=t.location.x, y=t.location.y, z=t.location.z + 0.3),
        t.rotation,
    )

def _driving_adjacent_lanes(wpt):
    lanes = []
    for getter in (wpt.get_left_lane, wpt.get_right_lane):
        try: lane = getter()
        except RuntimeError: lane = None
        if lane and lane.lane_type == carla.LaneType.Driving:
            lanes.append(lane)
    return lanes

def _same_lane(a, b):
    return bool(a and b and a.road_id == b.road_id and a.lane_id == b.lane_id)

def _lane_distance(a, b):
    al = a.transform.location; bl = b.transform.location
    return float(np.hypot(al.x - bl.x, al.y - bl.y))

def signed_longitudinal_offset(ref, ego):
    rl = ref._carla_vehicle.get_location(); el = ego._carla_vehicle.get_location()
    yaw = math.radians(ref._carla_vehicle.get_transform().rotation.yaw)
    fwd = np.array([math.cos(yaw), math.sin(yaw)])
    return float(np.dot(np.array([rl.x - el.x, rl.y - el.y]), fwd))

def signed_lateral_offset(ref, ego):
    rl = ref._carla_vehicle.get_location(); el = ego._carla_vehicle.get_location()
    yaw = math.radians(ref._carla_vehicle.get_transform().rotation.yaw)
    side = np.array([math.sin(yaw), -math.cos(yaw)])
    return float(np.dot(np.array([el.x - rl.x, el.y - rl.y]), side))

def _set_gap(v, g): v.desired_gap_m = float(g)

def v_ref_cacc(pre, ego):
    gap = ego.distance_to(pre); vp = pre.speed; ve = ego.speed
    desired = getattr(ego, "desired_gap_m", NORMAL_FOLLOW_GAP_M)
    v = vp + 0.55 * (gap - desired) + 0.80 * (vp - ve)
    return float(np.clip(v * 3.6, max(5.0, vp * 3.6 - 14.0), vp * 3.6 + 20.0))

def compute_lead_route(cmap, loc, dist=3000.0, step=5.0):
    route = deque()
    cur = cmap.get_waypoint(loc, project_to_road=True, lane_type=carla.LaneType.Driving)
    if not cur: return route
    route.append(cur); rem = dist
    while rem > 0:
        nxt = cur.next(min(step, rem))
        if not nxt: break
        cur = _select_straight(nxt, cur.transform.rotation.yaw)
        route.append(cur); rem -= step
    return route

def _make_pid(carla_vehicle):
    lat = {"K_P": 5.5, "K_I": 0.2,  "K_D": 0.4, "dt": DT}   # ⚠️ 강력한 조향
    lon = {"K_P": 1.0, "K_I": 0.2,  "K_D": 0.05, "dt": DT}  # ⚠️ 종방향 응답성 강화
    return nav_controller.VehiclePIDController(
        carla_vehicle, args_lateral=lat, args_longitudinal=lon,
        max_brake=0.4, max_throttle=1.0,                    # ⚠️ 가속력 최대
    )

# ── 브리지 헬퍼 ───────────────────────────────────────────────────────────────
import subprocess

def _get_docker_status():
    """각 트럭별 docker 상태 반환: {"truck1": "Up 2m", "truck3": "없음", ...}"""
    result = {"truck1": "없음", "truck3": "없음"}
    try:
        for name in ("openclaw-truck1", "openclaw-truck3"):
            r = subprocess.run(
                ["docker", "ps", "--all", "--filter", f"name=^/{name}$",
                 "--format", "{{.Status}}"],
                capture_output=True, text=True, timeout=1)
            s = r.stdout.strip()
            key = "truck1" if "truck1" in name else "truck3"
            result[key] = s if s else "없음"
    except Exception:
        pass
    return result

def _bridge_post(path, body=None):
    try:
        req = urllib.request.Request(
            BRIDGE_URL + path,
            data=json.dumps(body or {}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as r:
            return json.loads(r.read().decode())
    except Exception: return None

def _bridge_reload():
    res = _bridge_post("/reload", {})
    print("[bridge] 상태 리셋 완료" if res else "[bridge] 서버 응답 없음")

# ── HTTP 트리거 서버 ──────────────────────────────────────────────────────────
def _start_trigger_server():
    class BranchHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200); self.end_headers()
            if self.path.rstrip("/") in ("/start_merge", "/branch"):
                _branch_trigger_event.set()
                print("\n[18802] 분기 트리거 수신!")
            elif self.path.rstrip("/") == "/start_replicate":
                _replicate_only_event.set()
                print("\n[18802] 복제 전용 트리거 수신 (분기는 truck3 부팅 후 자동)")
            elif "/complete" in self.path:
                _branch_complete_event.set()
        def log_message(self, *a): pass

    def _serve():
        try: HTTPServer(("0.0.0.0", TRIGGER_PORT), BranchHandler).serve_forever()
        except OSError as e: print(f"[trigger] 포트 {TRIGGER_PORT} 실패: {e}")
    threading.Thread(target=_serve, daemon=True).start()
    print(f"[trigger] {TRIGGER_PORT} 대기 중")

# ── 군집 빌드 (improve build_truck_platoon 그대로) ────────────────────────────
def build_platoon(sim, bp, spawn):
    p = Core.Platoon(sim)
    lead = p.add_lead_vehicle(bp, spawn); sim.tick()
    lead.attach_controller(PlatooningControllers.LeadNavigator(lead, initial_speed=SYNC_SPEED_KMH))
    anchor_wpt = sim.map.get_waypoint(
        lead.get_location(), project_to_road=True, lane_type=carla.LaneType.Driving
    )
    for i in range(PLATOON_SIZE - 1):
        fwpt = _retreat_waypoint(anchor_wpt, PLATOON_SPACING_M * (i + 1))
        fsp  = _spawn_from_waypoint(fwpt) if fwpt else spawn
        f = p.add_follower_vehicle(bp, fsp)
        _set_gap(f, NORMAL_FOLLOW_GAP_M)
        f.attach_controller(PlatooningControllers.FollowerController(
            f, v_ref_cacc, p, dependencies=[-1, 0]
        ))
        sim.tick()
    p.store_follower_waypoints()
    p.lead_waypoints.append(anchor_wpt)
    return p

# ── 분기 상태 머신 ────────────────────────────────────────────────────────────
class BranchState(Enum):
    CRUISE = auto()
    MIGRATE = auto()
    GAP    = auto()
    LC     = auto()
    SIDE_BY_SIDE = auto()  # ⚠️ 나란히 가기 상태 추가
    DONE   = auto()

class BranchCoordinator:
    """
    improve의 TransferCoordinator 패턴을 따름.
    truck2(후미) → 옆 차선 분기.
    CRUISE → MIGRATE → GAP → LC → DONE
    """
    def __init__(self, platoon, cmap, sim, replicator=None):
        self.platoon    = platoon
        self.cmap       = cmap
        self.sim        = sim
        self.replicator = replicator
        self.state      = BranchState.CRUISE
        self.triggered  = False
        self._v         = None    # truck2 (분리된 후미)
        self._v_platoon = None    # truck2를 담은 새 군집
        self._pid       = None
        self._ticks     = 0
        self._gap_ok    = 0
        self._target_lane_id = None
        self._target_lane_wpt = None
        self.last_status = "idle"

    def trigger(self):
        if self.state == BranchState.CRUISE:
            self.triggered = True

    def camera_target(self):
        if self._v and self.state not in (BranchState.CRUISE, BranchState.MIGRATE):
            return self._v._carla_vehicle
        return self.platoon[0]._carla_vehicle

    def update(self, step):
        if self.state == BranchState.CRUISE:
            if self.triggered: self._start_migrate()
        elif self.state == BranchState.MIGRATE:
            # wait(timeout=0)으로 비차단 체크
            if self.replicator and self.replicator.wait(timeout=0):
                print("[branch] OpenClaw 복제 완료 → GAP 확보")
                self.state = BranchState.GAP
            elif self.replicator is None:
                self.state = BranchState.GAP
        elif self.state == BranchState.GAP:    self._update_gap()
        elif self.state == BranchState.LC:     self._update_lc()
        elif self.state == BranchState.SIDE_BY_SIDE: self._update_side_by_side()

    def _start_migrate(self):
        print("\n[branch] 분기 트리거!")
        _bridge_post("/branch", {"vehicle":"truck2","status":"started"})
        if self.replicator:
            if self.replicator.wait(timeout=0):
                # 복제가 이미 완료됨 (watch_truck3 자동 트리거 경로)
                print("[branch] 복제 이미 완료 → 바로 GAP 확보 시작")
                self.state = BranchState.GAP
            else:
                self.replicator.replicate(blocking=False)
                self.state = BranchState.MIGRATE
        else:
            print("[branch] replicator 없음 — OpenClaw 복제 스킵")
            self.state = BranchState.GAP

    def _update_gap(self):
        if self._v is None:
            # truck2 분리 (index 2)
            self._v_platoon, _ = self.platoon.split(2, 2)
            self._v = self._v_platoon[0]
            
            # truck2 제어를 위해 PID 생성
            self._v.attach_controller(None)
            self._pid = _make_pid(self._v._carla_vehicle)
            print(f"[branch] truck2 분리. 잔여 군집: {len(self.platoon)}대")
            self.last_status = "gap_opening"
            return

        # 앞차(truck1)와의 간격 확보
        tail = self.platoon[-1]  # truck1
        gap = tail.distance_to(self._v)
        
        if gap >= OPEN_GAP_READY_M: self._gap_ok += 1
        else: self._gap_ok = 0

        ego_wpt = self.cmap.get_waypoint(self._v.get_location())
        if ego_wpt:
            target_wpt = _advance_waypoint(ego_wpt, 10.0)    # ⚠️ 20m -> 10m (응답성)
            # truck2 감속 (40% 속도) 하여 빠르게 간격 벌림
            ctrl = self._pid.run_step(SYNC_SPEED_KMH * 0.4, target_wpt)
            self._v.apply_control(ctrl)

        self.last_status = f"gap={gap:.1f}/{OPEN_GAP_READY_M}m ok={self._gap_ok}"
        if self._gap_ok >= GAP_STABLE_TICKS:
            print(f"[branch] 간격 확보 완료 ({gap:.1f}m) → LC 시작")
            self._start_lc()

    def _start_lc(self):
        ego_wpt = self.cmap.get_waypoint(self._v.get_location())
        adj = _driving_adjacent_lanes(ego_wpt)
        if adj:
            self._target_lane_wpt = adj[0]
            self._target_lane_id = (self._target_lane_wpt.road_id, self._target_lane_wpt.lane_id)
            print(f"[branch] LC 시작: 목표 차선 road={self._target_lane_id[0]} lane={self._target_lane_id[1]}")
        else:
            print("[branch] 에러: 인접 차선 없음! 제자리에서 DONE 시도")
            self._target_lane_wpt = ego_wpt
            self._target_lane_id = (ego_wpt.road_id, ego_wpt.lane_id)

        self._ticks = 0
        self.state = BranchState.LC

    def _update_lc(self):
        self._ticks += 1
        ego_loc = self._v.get_location()
        ego_wpt = self.cmap.get_waypoint(ego_loc)
        
        # 목표 차선 추적
        target_wpt = _advance_waypoint(self._target_lane_wpt, 8.0)  # ⚠️ 20m -> 8m (날카로운 조향)
        self._target_lane_wpt = _advance_waypoint(self._target_lane_wpt, self._v.speed * DT)
        
        # 분기 시 속도 유지 또는 약간 가속
        v_cmd = SYNC_SPEED_KMH * 1.1
        ctrl = self._pid.run_step(v_cmd, target_wpt)
        self._v.apply_control(ctrl)

        # 차선 변경 완료 판정
        if ego_wpt.road_id == self._target_lane_id[0] and ego_wpt.lane_id == self._target_lane_id[1]:
            print(f"[branch] 차선 변경 완료 → SIDE_BY_SIDE (나란히 가기 시작)")
            self.state = BranchState.SIDE_BY_SIDE
            self._ticks = 0
            return

        if self._ticks > 2000:
            print(f"[branch] LC 타임아웃 → SIDE_BY_SIDE 강제 전환")
            self.state = BranchState.SIDE_BY_SIDE
            self._ticks = 0
            return

        self.last_status = f"LC ticks={self._ticks}"

    def _update_side_by_side(self):
        self._ticks += 1
        lead_v = self.platoon[0]
        
        # ⚠️ 따라잡기를 돕기 위해 원래 군집의 속도를 잠시 늦춤
        if lead_v.controller.target_speed > SYNC_SPEED_KMH * 0.75:
            lead_v.controller.set_target_speed(SYNC_SPEED_KMH * 0.75)
        
        # 목표 차선(옆 차선) 유지
        target_wpt = _advance_waypoint(self._target_lane_wpt, 15.0)
        self._target_lane_wpt = _advance_waypoint(self._target_lane_wpt, self._v.speed * DT)
        
        # ⚠️ 위치 오차 계산 (longitudinal offset)
        off = signed_longitudinal_offset(lead_v, self._v)
        
        # ⚠️ 공격적인 따라잡기 로직 (Catch-up)
        # 리더보다 뒤에 있으면(off > 2.0) 최대 120km/h까지 가속하여 빠르게 정렬
        if off > 2.0:
            v_cmd = SYNC_SPEED_KMH * 2.0        # 따라잡기: 동기 속도의 2배
            self._ticks = 0                     # 정렬될 때까지 시간 카운트 리셋
        elif off < -2.0:
            v_cmd = lead_v.speed * 3.6 - 10.0   # 너무 앞서면 감속
        else:
            v_cmd = lead_v.speed * 3.6          # 유지
            
        v_cmd = np.clip(v_cmd, 5.0, SYNC_SPEED_KMH * 2.0)
        ctrl = self._pid.run_step(float(v_cmd), target_wpt)
        self._v.apply_control(ctrl)
        
        # 정렬된 상태(off < 2.5)가 5초(500틱) 유지되면 최종 분리
        if abs(off) < 2.5 and self._ticks > 500:
            print("[branch] 나란히 주행 완료 → DONE (최종 분리)")
            # 속도 원복
            lead_v.controller.set_target_speed(SYNC_SPEED_KMH)
            self._finalize()
            return
            
        self.last_status = f"SIDE_BY_SIDE off={off:.1f}m v={v_cmd:.1f} ticks={self._ticks}"

    def _finalize(self):
        # 분리된 truck2에게 LeadNavigator 부여하여 계속 주행하게 함
        nav = PlatooningControllers.LeadNavigator(self._v._carla_vehicle, initial_speed=SYNC_SPEED_KMH)
        self._v.attach_controller(nav)
        nav.waypoints_ahead = compute_lead_route(self.cmap, self._v.get_location())
        
        _bridge_post("/branch", {"vehicle":"truck2","status":"complete"})
        _branch_complete_event.set()
        self.state = BranchState.DONE
        print("[branch] >>> 분기 완료! truck2 독립 주행 시작")

    def status_line(self):
        return f"{self.state.name} {self.last_status}"

# ── SmoothCamera (개선: 두 군집을 모두 담기 위해 중간 지점 추적) ──────────────────
class SmoothCamera:
    def __init__(self, s, coordinator): 
        self.s = s
        self.coord = coordinator
        self.x = self.y = None
        
    def update(self, _unused_target):
        # ⚠️ 나란히 가는 상황에서는 두 차량의 중간 지점을 추적
        lead_v = self.coord.platoon[0]
        branch_v = self.coord._v
        
        if branch_v and self.coord.state == BranchState.SIDE_BY_SIDE:
            l1 = lead_v.get_location()
            l2 = branch_v.get_location()
            # 중간 지점
            tx, ty = (l1.x + l2.x) / 2, (l1.y + l2.y) / 2
            z_offset = 75  # 나란히 주행 시 약간 더 높게
        else:
            loc = lead_v.get_location()
            tx, ty = loc.x, loc.y
            z_offset = 60
            
        if self.x is None: self.x, self.y = tx, ty
        self.x += 0.05 * (tx - self.x); self.y += 0.05 * (ty - self.y)
        
        self.s.set_transform(carla.Transform(
            carla.Location(x=self.x, y=self.y, z=lead_v.get_location().z + z_offset),
            carla.Rotation(pitch=-90),
        ))

# ── KeyInput ─────────────────────────────────────────────────────────────────
class KeyInput:
    def __init__(self):
        self._active = False
        try:
            self._fd = sys.stdin.fileno(); self._old = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd); self._active = True
            print("[keys] '3'=분기  Ctrl-C=종료")
        except termios.error:
            print("[keys] TTY 없음 — 키보드 비활성화")
    def read(self):
        if not self._active: return ""
        if select.select([sys.stdin], [], [], 0)[0]:
            ch = sys.stdin.read(1)
            if ch == "\x03": self.restore(); raise KeyboardInterrupt
            return ch
        return ""
    def restore(self):
        if self._active:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old); self._active = False

# ── main ─────────────────────────────────────────────────────────────────────
def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--no-openclaw",    action="store_true")
    p.add_argument("--auto-trigger-s", type=float, default=0.0)
    args = p.parse_args()

    # ── watch 스크립트 로그 초기화 (이전 실행 잔존 방지) ────────────────────────
    _watch_logs = [
        _PROJECT / ".transfer" / "telemetry.log",
        _PROJECT / ".transfer" / "tx" / ".progress.log",
        _PROJECT / ".transfer" / "rx" / ".progress.log",
    ]
    for _p in _watch_logs:
        try:
            if _p.exists():
                _p.write_text("")
        except Exception:
            pass

    _bridge_reload()
    _start_trigger_server()

    # CARLA 초기화 (improve 패턴)
    sim  = Core.Simulation(world="Town06", dt=DT, synchronous=True)
    # 어두운 석양 날씨
    sim.world.set_weather(carla.WeatherParameters.CloudySunset)

    cmap = sim.map
    bps  = sim.get_vehicle_blueprints()
    
    # ⚠️ 철통 로직: 여러 후보 중 존재하는 첫 번째 트럭 모델 선택
    truck_candidates = [
        "vehicle.carlamotors.european_hgv",
        "vehicle.mercedes-benz.actros",
        "vehicle.carlamotors.carlacola",
        "vehicle.carlamotors.firetruck"
    ]
    
    bp = None
    for cand in truck_candidates:
        found = bps.filter(cand)
        if found:
            bp = found[0]
            break
            
    if not bp:
        # 최후의 수단: 이름에 'truck'이 들어간 아무 모델이나 선택
        bp = bps.filter("*truck*")[0]
        
    print(f"[main] blueprint selected: {bp.id}")

    platoon = build_platoon(sim, bp, PLATOON_SPAWN)
    platoon[0].controller.waypoints_ahead = compute_lead_route(cmap, platoon[0].get_location())
    print(f"[main] 군집 생성: {PLATOON_SIZE}대  spawn=({_p1['x']},{_p1['y']})")
    print(f"  truck0(선두) → truck1 → truck2(후미)")

    # OpenClaw BranchReplicator
    replicator = None
    if not args.no_openclaw:
        try:
            from replicator import BranchReplicator
            replicator = BranchReplicator(
                source_truck_id="truck0", branch_truck_id="truck2",
                branch_agent_dir=_PROJECT / "agents" / "truck2",
                source_openclaw_data_dir=_PROJECT / ".openclaw-truck0",
                branch_openclaw_data_dir=_PROJECT / ".openclaw-truck2",
            )
            print("[main] BranchReplicator 준비 완료")
        except ImportError:
            print("[main] replicator 없음 — OpenClaw 스킵")

    coord  = BranchCoordinator(platoon, cmap, sim, replicator=replicator)
    camera = SmoothCamera(sim.spectator, coord)
    kb     = KeyInput()

    step = 0; auto_triggered = False

    def speeds(): return ", ".join(f"t{i}={v.speed*3.6:.1f}" for i, v in enumerate(platoon))
    def gaps():
        vs = list(platoon)
        return ", ".join(f"{vs[i].distance_to(vs[i+1]):.1f}" for i in range(len(vs)-1)) if len(vs) > 1 else "-"

    try:
        while True:
            if step * DT > 600.0: break

            key = kb.read()
            if key == "3" and coord.state == BranchState.CRUISE:
                print("\n[키] 3 — 분기 트리거"); coord.trigger()

            if (args.auto_trigger_s > 0 and not auto_triggered
                    and step * DT >= args.auto_trigger_s and coord.state == BranchState.CRUISE):
                print(f"\n[auto] {args.auto_trigger_s}s — 자동 트리거")
                coord.trigger(); auto_triggered = True

            if _branch_trigger_event.is_set() and coord.state == BranchState.CRUISE:
                _branch_trigger_event.clear(); coord.trigger()

            # 복제 전용 트리거: 분기는 watch_truck3 가 openclaw-truck3 부팅 후 /start_merge 전송
            if _replicate_only_event.is_set() and replicator and not replicator.wait(timeout=0):
                _replicate_only_event.clear()
                print("\n[복제] OpenClaw 복제 시작 (분기는 truck3 부팅 후 자동 발동)")
                replicator.replicate(blocking=False)

            coord.update(step)
            sim.run_step(mode="sample" if step % SAMPLING_RATE == 0 else "control")
            sim.tick()
            camera.update(None)

            if step % 100 == 0:
                d_status = _get_docker_status()
                t1_doc = "Up" if "Up" in d_status["truck1"] else "없음"
                t3_doc = "Up" if "Up" in d_status["truck3"] else "없음"
                branch_state = coord.state.name
                telem = (
                    f"t={step*DT:6.1f}s "
                    f"speeds=({speeds()}) "
                    f"gaps=({gaps()}) "
                    f"truck1=[openclaw:{t1_doc}] "
                    f"truck2=[none] "
                    f"truck3=[openclaw:{t3_doc}] "
                    f"state={branch_state}"
                )
                print(telem)
                # watch 스크립트들이 읽는 텔레메트리 로그
                _telem_log = _PROJECT / ".transfer" / "telemetry.log"
                _telem_log.parent.mkdir(parents=True, exist_ok=True)
                with open(_telem_log, "a") as _tf:
                    _tf.write(telem + "\n")

            if coord.state == BranchState.DONE and not auto_triggered:
                print("[main] 분기 완료! 계속 주행...")
                auto_triggered = True  # 메시지 중복 방지

            step += 1
    finally:
        kb.restore()
        sim.release_synchronous()
        # watch 스크립트 로그 초기화 (Ctrl+C 후 재시작 시 잔존 방지)
        for _p in _watch_logs:
            try:
                if _p.exists():
                    _p.write_text("")
            except Exception:
                pass

if __name__ == "__main__":
    main()
