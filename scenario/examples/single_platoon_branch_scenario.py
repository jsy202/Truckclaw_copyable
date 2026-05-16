"""
Single-Platoon Branch Scenario — CARLA 0.9.6 + OpenClaw 연동
improve 레포(jsy202/Truckclaw-improve) two_platoon_truck_scenario.py 로직 직접 이식.
p1_spawn(x=81,y=136)에서 3대 군집 출발 → truck_3이 30초 후 차선변경으로 분기.

OpenClaw 연동 흐름:
  1. 시나리오 시작 → Replicator.replicate() 백그라운드 실행 (truck_1 → truck_3 복제)
  2. OpenClaw 에이전트들이 Discord에서 협상
  3. truck_3 에이전트가 bridge POST /commit → bridge가 18802 트리거
  4. 18802 수신 → coord.trigger() → GAP 확보 → 차선변경
"""
from __future__ import annotations
import glob, json, math, os, select, sys, termios, threading, tty, urllib.request
from collections import deque
from enum import Enum, auto
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

try:
    sys.path.append(glob.glob(
        '/opt/carla-0.9.6/PythonAPI/carla/dist/carla-*%d.%d-%s.egg' % (
            sys.version_info.major, sys.version_info.minor,
            'win-amd64' if os.name == 'nt' else 'linux-x86_64'))[0])
except IndexError: pass
sys.path.append('/opt/carla-0.9.6/PythonAPI/carla')

import carla
import numpy as np
from agents.navigation import controller as nav_controller

_PROJECT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT))
sys.path.insert(0, str(Path(__file__).parent / ".." / "src"))
sys.path.insert(0, str(_PROJECT / "openclaw_migration"))
from PlatooningSimulator import Core, PlatooningControllers

# ── config (improve 레포 simulation.json 그대로) ──────────────────────────────
_CFG = json.loads((_PROJECT / "config" / "simulation.json").read_text())
_spd = _CFG["speeds"]; _gap = _CFG["gaps"]; _sp = _CFG["spawns"]

DT                  = 0.01
SAMPLING_RATE       = 10
PLATOON_SIZE        = 3
PLATOON_SPACING_M   = float(_gap["platoon_spacing_m"])      # 18
NORMAL_FOLLOW_GAP_M = float(_gap["normal_follow_gap_m"])    # 12
OPEN_GAP_M          = float(_gap["open_gap_m"])             # 20
OPEN_GAP_READY_M    = float(_gap["open_gap_ready_m"])       # 18
SYNC_SPEED_KMH      = 15.0   # 속도 낮춤 (18 → 15 km/h)
MERGE_MIN_SPEED_KMH = float(_spd["merge_min_speed_kmh"])    # 15
TARGET_GAP_M        = float(_gap["target_gap_m"])           # 13
LANE_STEP_COMPLETE_M = 0.9
BRANCH_AUTO_S        = 0.0    # 0 = 자동 타이머 비활성화 (OpenClaw 트리거만 사용)

# ── OpenClaw 연동 설정 ────────────────────────────────────────────────────────
BRIDGE_URL     = "http://127.0.0.1:18801"
TRIGGER_PORT   = 18802          # 브리지 → CARLA 트리거 수신 포트
ENABLE_OPENCLAW = True          # False 로 설정시 순수 CARLA 모드 (키보드/자동 트리거만)

# bridge 에 등록할 platoon/vehicle ID (platoon_destinations.json 과 일치)
BRANCH_PLATOON_ID  = "platoon_a"
BRANCH_TARGET_ID   = "platoon_b"   # 분기 후 합류 목표 (논리적 용도)
BRANCH_VEHICLE_ID  = "platoon_a_truck2"   # truck_3 → index=2

# 공식 스폰포인트 사용 (z=2.5 확보, 벽 박힘 방지)
# improve 레포 p1_spawn x=81,y=136 → 실제 가장 가까운 공식 스폰: x=93.8,y=136.3,z=2.5
PLATOON_SPAWN = carla.Transform(
    carla.Location(x=93.8, y=136.3, z=2.5),
    carla.Rotation(pitch=0.0, yaw=0.2, roll=0.0))

# ── improve 레포 헬퍼 함수 그대로 ────────────────────────────────────────────
def _yaw_diff(a, ref): return abs((a - ref + 180.0) % 360.0 - 180.0)
def _select_straight(cands, yaw): return min(cands, key=lambda w: _yaw_diff(w.transform.rotation.yaw, yaw)) if cands else None

def _advance_waypoint(wpt, dist):
    cur = wpt; rem = float(dist)
    while rem > 0.0:
        step = min(10.0, rem)
        nxt = cur.next(step)
        if not nxt: return cur
        cur = _select_straight(nxt, cur.transform.rotation.yaw)
        rem -= step
    return cur

def _spawn_from_waypoint(wpt):
    t = wpt.transform
    return carla.Transform(carla.Location(x=t.location.x, y=t.location.y, z=t.location.z+0.3), t.rotation)

def _driving_adjacent_lanes(wpt):
    lanes = []
    for getter in (wpt.get_left_lane, wpt.get_right_lane):
        try: lane = getter()
        except RuntimeError: lane = None
        if lane and lane.lane_type == carla.LaneType.Driving:
            lanes.append(lane)
    return lanes

def _lane_distance(a, b):
    al = a.transform.location; bl = b.transform.location
    return float(np.hypot(al.x - bl.x, al.y - bl.y))

def _same_lane(a, b):
    return bool(a and b and a.road_id == b.road_id and a.lane_id == b.lane_id)

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

# improve 레포 _one_lane_step_target 그대로
def _one_lane_step_target(cmap, ego_v, receiver_ref_wpt, signed_offset_m):
    ego_wpt = cmap.get_waypoint(ego_v._carla_vehicle.get_location(),
        project_to_road=True, lane_type=carla.LaneType.Driving)
    if signed_offset_m > 0.0:
        target_wpt = _advance_waypoint(receiver_ref_wpt, signed_offset_m) or receiver_ref_wpt
    else:
        target_wpt = receiver_ref_wpt
    if not ego_wpt or not target_wpt: return target_wpt
    if _same_lane(ego_wpt, target_wpt): return target_wpt
    adjacent = _driving_adjacent_lanes(ego_wpt)
    if not adjacent: return ego_wpt
    step_lane = min(adjacent, key=lambda lane: _lane_distance(lane, target_wpt))
    return _advance_waypoint(step_lane, signed_offset_m) or step_lane

def _set_gap(v, g): v.desired_gap_m = float(g)

def v_ref_cacc(pre, ego):
    gap = ego.distance_to(pre); vp = pre.speed; ve = ego.speed
    desired = getattr(ego, "desired_gap_m", NORMAL_FOLLOW_GAP_M)
    v = vp + 0.55*(gap-desired) + 0.80*(vp-ve)
    return float(np.clip(v*3.6, max(5.0, vp*3.6-14.0), vp*3.6+20.0))

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
    import inspect
    sig = inspect.signature(nav_controller.VehiclePIDController.__init__)
    lat = {"K_P": 3.2, "K_I": 0.1,  "K_D": 0.25, "dt": DT}
    lon = {"K_P": 0.65,"K_I": 0.15, "K_D": 0.05,  "dt": DT}
    if "max_brake" in sig.parameters:
        return nav_controller.VehiclePIDController(carla_vehicle,
            args_lateral=lat, args_longitudinal=lon, max_brake=0.4, max_throttle=0.8)
    return nav_controller.VehiclePIDController(carla_vehicle,
        args_lateral=lat, args_longitudinal=lon)

# ── OpenClaw / 브리지 헬퍼 ────────────────────────────────────────────────────
_branch_trigger_event   = threading.Event()
_replicate_trigger_event = threading.Event()

def _start_trigger_server():
    """포트 18802에서 브리지 트리거 수신.
    POST /start_merge    → 분기 트리거 (기존)
    POST /start_replicate → 복제 트리거 (OpenClaw가 요청)
    """
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            path = self.path.rstrip("/")
            if path == "/start_replicate":
                _replicate_trigger_event.set()
                self.send_response(200); self.end_headers()
                print("\n[18802] OpenClaw → 복제 트리거 수신!")
            else:  # /start_merge (기본)
                _branch_trigger_event.set()
                self.send_response(200); self.end_headers()
                print("\n[18802] 브리지에서 분기 트리거 수신!")
        def log_message(self, *a): pass
    def _serve():
        try:
            server = HTTPServer(("0.0.0.0", TRIGGER_PORT), H)
            print("[trigger] 18802 수신 대기 중... (/start_merge + /start_replicate)")
            server.serve_forever()
        except OSError as e:
            print(f"[trigger] 서버 시작 실패 (이미 사용 중?): {e}")
    threading.Thread(target=_serve, daemon=True).start()

def _bridge_post(path, body=None):
    try:
        req = urllib.request.Request(
            BRIDGE_URL + path,
            data=json.dumps(body or {}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=2) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return None

def _bridge_reload():
    res = _bridge_post("/reload", {})
    if res: print("[bridge] 상태 리셋 완료")
    else:   print("[bridge] 브리지 서버 응답 없음 (OpenClaw 없이 진행)")

def _bridge_register_transfer():
    """브리지에 transfer 등록 → OpenClaw 에이전트가 협상 후 commit."""
    res = _bridge_post("/transfers", {
        "vehicle_id":      BRANCH_VEHICLE_ID,
        "from_platoon_id": BRANCH_PLATOON_ID,
        "to_platoon_id":   BRANCH_TARGET_ID,
    })
    if res:
        print(f"[bridge] transfer 등록: {res['request_id']} (에이전트 협상 대기 중...)")
    else:
        print("[bridge] transfer 등록 실패 — 자동 타이머로 fallback")
    return res

def _start_replicator():
    """백그라운드에서 OpenClaw 복제 (truck_1 → truck_3)."""
    def _run():
        try:
            from replicator import Replicator
            print("[replicator] OpenClaw 복제 시작 (truck_1 → truck_3)...")
            r = Replicator()
            r.replicate()
            print("[replicator] 복제 완료 ✓ — 에이전트 협상 시작 가능")
        except ImportError:
            print("[replicator] replicator 모듈 없음 — 스킵")
        except Exception as e:
            print(f"[replicator] 복제 실패: {e} — 자동 트리거로 fallback")
    threading.Thread(target=_run, daemon=True).start()

# ── 군집 빌드 ─────────────────────────────────────────────────────────────────
def _spawn_behind(cmap, ref_wpt, dist):
    """ref_wpt 기준 후방 dist(m) 위치의 spawn Transform (도로 위, z+0.3)."""
    import math
    yaw_rad = math.radians(ref_wpt.transform.rotation.yaw)
    bx = ref_wpt.transform.location.x - math.cos(yaw_rad) * dist
    by = ref_wpt.transform.location.y - math.sin(yaw_rad) * dist
    bz = ref_wpt.transform.location.z
    wpt = cmap.get_waypoint(carla.Location(x=bx, y=by, z=bz),
        project_to_road=True, lane_type=carla.LaneType.Driving)
    if wpt:
        t = wpt.transform
        return carla.Transform(
            carla.Location(x=t.location.x, y=t.location.y, z=t.location.z + 0.3),
            t.rotation)
    # fallback
    return carla.Transform(
        carla.Location(x=bx, y=by, z=bz + 0.3),
        ref_wpt.transform.rotation)

def build_platoon(sim, bp, spawn):
    p = Core.Platoon(sim)
    lead = p.add_lead_vehicle(bp, spawn); sim.tick()
    lead.attach_controller(PlatooningControllers.LeadNavigator(lead, initial_speed=SYNC_SPEED_KMH))
    # lead waypoint 기준으로 정확히 후방 배치
    lead_wpt = sim.map.get_waypoint(lead.get_location(),
        project_to_road=True, lane_type=carla.LaneType.Driving)
    for i in range(PLATOON_SIZE - 1):
        fsp = _spawn_behind(sim.map, lead_wpt, PLATOON_SPACING_M * (i + 1))
        f = p.add_follower_vehicle(bp, fsp); _set_gap(f, NORMAL_FOLLOW_GAP_M)
        f.attach_controller(PlatooningControllers.FollowerController(
            f, v_ref_cacc, p, dependencies=[-1, 0]))
        sim.tick()
    p.store_follower_waypoints()
    p.lead_waypoints.append(lead_wpt)
    return p

# ── 상태 머신 (improve 레포 TransferState 단순화) ─────────────────────────────
class BranchState(Enum):
    CRUISE = auto()
    GAP    = auto()
    LC     = auto()
    DONE   = auto()

GAP_STABLE_TICKS = 50

class BranchCoordinator:
    def __init__(self, platoon, cmap, sim):
        self.platoon = platoon; self.cmap = cmap; self.sim = sim
        self.state = BranchState.CRUISE; self.triggered = False
        self._gap_ok = 0; self._detached = None; self._pid = None; self._ticks = 0

    def trigger(self):
        if self.state == BranchState.CRUISE: self.triggered = True

    def update(self, step):
        if self.state == BranchState.CRUISE and self.triggered:
            print("\n[branch] GAP 확보 시작 (t=%.1fs)" % (step*DT))
            _set_gap(self.platoon[2], OPEN_GAP_M)
            self.state = BranchState.GAP

        elif self.state == BranchState.GAP:
            gap = self.platoon[1].distance_to(self.platoon[2])
            if gap >= OPEN_GAP_READY_M: self._gap_ok += 1
            else: self._gap_ok = 0
            if self._gap_ok >= GAP_STABLE_TICKS:
                print("[branch] 간격 %.1fm 확보 → 차선변경 시작" % gap)
                self._start_lc()

        elif self.state == BranchState.LC:
            self._update_lc()

        elif self.state == BranchState.DONE:
            self._update_done()

    def _start_lc(self):
        new_p, _ = self.platoon.split(2, 2)
        self._detached = new_p[0]
        try: self.sim.platoons.remove(new_p)
        except ValueError: pass
        self._detached.attach_controller(None)
        self._detached._carla_vehicle.apply_control(
            carla.VehicleControl(throttle=0.25, brake=0.0, hand_brake=False))
        self._pid = _make_pid(self._detached._carla_vehicle)
        self._ticks = 0

        # 분기 목표 차선 waypoint 미리 고정
        # 현재 ego waypoint의 인접 차선 중 하나를 목표로 설정
        ego_wpt = self.cmap.get_waypoint(
            self._detached._carla_vehicle.get_location(),
            project_to_road=True, lane_type=carla.LaneType.Driving)
        self._target_lane_wpt = None
        if ego_wpt:
            adjacent = _driving_adjacent_lanes(ego_wpt)
            if adjacent:
                # 인접 차선 중 첫 번째 (left lane 우선)
                self._target_lane_wpt = adjacent[0]
                print("[branch] 목표 차선: road=%d lane=%d" % (
                    self._target_lane_wpt.road_id, self._target_lane_wpt.lane_id))

        self.state = BranchState.LC
        print("[branch] truck_3 분리 → PID 차선변경")
        print("[branch] 남은 군집: %d대" % len(self.platoon))

    def _update_lc(self):
        if not self._detached: return
        self._ticks += 1
        tail = self.platoon[-1]
        rs  = tail.speed * 3.6

        # 목표: 고정된 인접 차선을 따라 전진
        if self._target_lane_wpt:
            ego_loc = self._detached._carla_vehicle.get_location()
            # 현재 위치에서 목표 차선 위의 가장 가까운 waypoint 찾기
            ego_wpt = self.cmap.get_waypoint(ego_loc,
                project_to_road=True, lane_type=carla.LaneType.Driving)
            # 목표 lane_id로 직접 이동
            target_wpt = self.cmap.get_waypoint(
                carla.Location(
                    x=ego_loc.x + 20.0 * __import__('math').cos(
                        __import__('math').radians(
                            self._detached._carla_vehicle.get_transform().rotation.yaw)),
                    y=self._target_lane_wpt.transform.location.y,
                    z=self._target_lane_wpt.transform.location.z),
                project_to_road=True, lane_type=carla.LaneType.Driving)
            if not target_wpt:
                target_wpt = _advance_waypoint(self._target_lane_wpt, 20.0)
        else:
            ego_wpt = self.cmap.get_waypoint(
                self._detached._carla_vehicle.get_location(),
                project_to_road=True, lane_type=carla.LaneType.Driving)
            adjacent = _driving_adjacent_lanes(ego_wpt) if ego_wpt else []
            target_wpt = _advance_waypoint(adjacent[0], 20.0) if adjacent else ego_wpt

        v_cmd = max(rs, SYNC_SPEED_KMH)
        ctrl = self._pid.run_step(float(v_cmd), target_wpt)
        ctrl.hand_brake = False
        self._detached._carla_vehicle.apply_control(ctrl)

        # 완료: lateral offset >= 2.5m (차선 폭 3.5m)
        ego_now = self.cmap.get_waypoint(
            self._detached._carla_vehicle.get_location(),
            project_to_road=True, lane_type=carla.LaneType.Driving)
        tail_wpt = self.cmap.get_waypoint(
            tail._carla_vehicle.get_location(),
            project_to_road=True, lane_type=carla.LaneType.Driving)
        lat = signed_lateral_offset(tail, self._detached)

        # 완료 조건: lateral >= 2.5m (차선 폭 3.5m의 70%)
        done = abs(lat) >= 2.5
        timeout = self._ticks > 2000

        if done or timeout:
            reason = "차선변경 완료" if done else "타임아웃"
            print("[branch] %s → DONE  ticks=%d lat=%.2f" % (reason, self._ticks, lat))
            # autopilot 대신 PID로 현재 속도 유지하며 직진
            # DONE 상태에서도 _update_done()으로 계속 제어
            self.state = BranchState.DONE

    def _update_done(self):
        """DONE 후 truck_3을 현재 속도 유지하며 PID 직진 제어."""
        if not self._detached or not self._pid:
            return
        ego_wpt = self.cmap.get_waypoint(
            self._detached._carla_vehicle.get_location(),
            project_to_road=True, lane_type=carla.LaneType.Driving)
        if not ego_wpt:
            return
        target_wpt = _advance_waypoint(ego_wpt, 20.0)
        v_cmd = SYNC_SPEED_KMH  # 군집과 같은 속도 유지
        ctrl = self._pid.run_step(float(v_cmd), target_wpt)
        ctrl.hand_brake = False
        self._detached._carla_vehicle.apply_control(ctrl)

    def camera_target(self):
        if self._detached and self.state == BranchState.LC:
            return self._detached._carla_vehicle
        return self.platoon[0]._carla_vehicle

    def status_line(self):
        if self.state == BranchState.GAP and len(self.platoon) >= 3:
            return "GAP %.1f/%.1fm ok=%d" % (
                self.platoon[1].distance_to(self.platoon[2]), OPEN_GAP_READY_M, self._gap_ok)
        if self.state == BranchState.LC and self._detached:
            tail = self.platoon[-1]
            return "LC off=%.1f lat=%.2f t=%d" % (
                signed_longitudinal_offset(tail, self._detached),
                signed_lateral_offset(tail, self._detached), self._ticks)
        return self.state.name

    def reset_actors(self):
        for v in list(self.platoon):
            try: v._carla_vehicle.destroy()
            except: pass
        if self._detached:
            try: self._detached._carla_vehicle.destroy()
            except: pass

# ── 군집 분기점 이탈 코디네이터 ──────────────────────────────────────────────
# truck_3 분기(DONE) 후 남은 2대 군집이 x≈600 도달 시 lane=-3 → lane=-4 로
# 차선변경해 분기 경로(남쪽)로 진입한다.
#
# Town06 도로 구조 (스폰 x=93 기준):
#   lane=-3  직진 → x≈658 junction → road=5 lane=3 남쪽
#   lane=-4  직진 → x≈650 이후    → road=5 lane=4 남쪽 (분기 경로)
# 차선변경 가능 구간: x=610~652 (right lane=-4 Driving 확인)
PLATOON_EXIT_TRIGGER_X = 600.0   # 이 x 좌표 통과 시 군집 차선변경 시작
PLATOON_EXIT_LAT_DONE  = 2.8     # lateral 이동 완료 판정 (차선폭 3.5m × 0.8)

class PlatoonExitState(Enum):
    WAIT   = auto()   # 분기점 도달 대기
    LC     = auto()   # 차선변경 중
    DONE   = auto()   # 완료

class PlatoonExitCoordinator:
    """truck_3 분기 후 남은 군집(lead+follower)이 분기점에서 lane=-4로 빠지는 코디네이터."""

    def __init__(self, platoon, cmap, sim):
        self.platoon  = platoon
        self.cmap     = cmap
        self.sim      = sim
        self.state    = PlatoonExitState.WAIT
        self._pids    = {}
        self._target_lane_wpt = None
        self._ticks   = 0

    def update(self):
        if self.state == PlatoonExitState.WAIT:
            self._check_trigger()
        elif self.state == PlatoonExitState.LC:
            self._update_lc()
        elif self.state == PlatoonExitState.DONE:
            self.apply_done_control()

    def _check_trigger(self):
        lead_loc = self.platoon[0]._carla_vehicle.get_location()
        if lead_loc.x >= PLATOON_EXIT_TRIGGER_X:
            print("\n[exit] 군집 분기점 접근 (x=%.0f) → lane=-4 차선변경 시작" % lead_loc.x)
            self._start_lc()

    def _start_lc(self):
        lead_wpt = self.cmap.get_waypoint(
            self.platoon[0]._carla_vehicle.get_location(),
            project_to_road=True, lane_type=carla.LaneType.Driving)
        self._target_lane_wpt = None
        if lead_wpt:
            try:
                right = lead_wpt.get_right_lane()
                if right and right.lane_type == carla.LaneType.Driving:
                    self._target_lane_wpt = right
                    print("[exit] 목표 차선: road=%d lane=%d y=%.1f" % (
                        right.road_id, right.lane_id, right.transform.location.y))
            except RuntimeError:
                pass

        if not self._target_lane_wpt:
            print("[exit] 인접 차선 없음 — 차선변경 스킵")
            self.state = PlatoonExitState.DONE
            return

        # platoon을 sim 루프에서 제거 → sim.run_step()이 더 이상 건드리지 않음
        try:
            self.sim.platoons.remove(self.platoon)
        except ValueError:
            pass

        # 각 차량에 독립 PID 부착
        for v in list(self.platoon):
            v.attach_controller(None)
            self._pids[v] = _make_pid(v._carla_vehicle)

        self.state  = PlatoonExitState.LC
        self._ticks = 0
        print("[exit] %d대 PID 전환 완료" % len(self._pids))

    def _update_lc(self):
        self._ticks += 1
        # 리드 차량 기준 lateral offset으로 완료 판정
        lead = self.platoon[0]
        all_done = True

        for v in list(self.platoon):
            pid = self._pids.get(v)
            if not pid:
                continue

            ego_loc = v._carla_vehicle.get_location()
            yaw_rad = math.radians(v._carla_vehicle.get_transform().rotation.yaw)

            # 목표 waypoint: target 차선의 y + 전방 20m
            target_wpt = self.cmap.get_waypoint(
                carla.Location(
                    x=ego_loc.x + 20.0 * math.cos(yaw_rad),
                    y=self._target_lane_wpt.transform.location.y,
                    z=self._target_lane_wpt.transform.location.z),
                project_to_road=True, lane_type=carla.LaneType.Driving)
            if not target_wpt:
                target_wpt = _advance_waypoint(self._target_lane_wpt, 20.0)

            ctrl = pid.run_step(float(SYNC_SPEED_KMH), target_wpt)
            ctrl.hand_brake = False
            v._carla_vehicle.apply_control(ctrl)

            # 완료 판정: ego waypoint의 lane_id가 목표 lane과 같으면 안착
            ego_wpt = self.cmap.get_waypoint(ego_loc,
                project_to_road=True, lane_type=carla.LaneType.Driving)
            if ego_wpt and ego_wpt.lane_id == self._target_lane_wpt.lane_id:
                pass  # 이 차량 완료
            else:
                all_done = False

        timeout = self._ticks > 3000

        if all_done or timeout:
            reason = "차선변경 완료" if all_done else "타임아웃"
            print("[exit] %s → DONE  ticks=%d" % (reason, self._ticks))
            self.state = PlatoonExitState.DONE

        if all_done or timeout:
            reason = "차선변경 완료" if all_done else "타임아웃"
            print("[exit] %s → DONE  ticks=%d" % (reason, self._ticks))
            self._finish()

    def _finish(self):
        """차선변경 완료 후 PID 직진 유지 (DONE에서 apply_done_control로 처리)."""
        self.state = PlatoonExitState.DONE
        print("[exit] 군집 lane=-4 안착 — PID 직진 유지")

    def is_done(self):
        return self.state == PlatoonExitState.DONE

    def apply_done_control(self):
        """DONE 상태에서도 PID로 현재 차선 직진."""
        for v, pid in self._pids.items():
            try:
                ego_wpt = self.cmap.get_waypoint(
                    v._carla_vehicle.get_location(),
                    project_to_road=True, lane_type=carla.LaneType.Driving)
                if not ego_wpt:
                    continue
                target_wpt = _advance_waypoint(ego_wpt, 20.0)
                ctrl = pid.run_step(float(SYNC_SPEED_KMH), target_wpt)
                ctrl.hand_brake = False
                v._carla_vehicle.apply_control(ctrl)
            except Exception:
                pass

    def status_line(self):
        if self.state == PlatoonExitState.WAIT:
            lead_x = self.platoon[0]._carla_vehicle.get_location().x
            return "EXIT_WAIT x=%.0f/%.0f" % (lead_x, PLATOON_EXIT_TRIGGER_X)
        if self.state == PlatoonExitState.LC:
            return "EXIT_LC ticks=%d" % self._ticks
        return "EXIT_DONE"

# ── 카메라 (improve 레포 SmoothCamera 그대로) ────────────────────────────────
class SmoothCamera:
    def __init__(self, s): self.s = s; self.x = self.y = None
    def update(self, t):
        loc = t.get_location()
        if self.x is None: self.x, self.y = loc.x, loc.y
        self.x += 0.05*(loc.x-self.x); self.y += 0.05*(loc.y-self.y)
        self.s.set_transform(carla.Transform(
            carla.Location(x=self.x, y=self.y, z=loc.z+85),
            carla.Rotation(pitch=-90)))

# ── 키 입력 ──────────────────────────────────────────────────────────────────
class KeyInput:
    def __init__(self):
        self._active = False
        try:
            self._fd = sys.stdin.fileno(); self._old = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd); self._active = True
            print("[keys] '3'=분기  'r'=리셋  Ctrl-C=종료")
        except termios.error:
            print("[keys] TTY 없음")
    def read(self):
        if not self._active: return ""
        if select.select([sys.stdin],[],[],0)[0]:
            ch = sys.stdin.read(1)
            if ch == "\x03": self.restore(); raise KeyboardInterrupt
            return ch
        return ""
    def restore(self):
        if self._active:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old); self._active = False

# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    sim  = Core.Simulation(world="Town06", dt=DT, synchronous=True, render=True)
    cmap = sim.map
    # 날씨: 대낮 (0.9.6 위치 인자)
    sim.world.set_weather(carla.WeatherParameters(5.0, 0.0, 0.0, 0.1, 220.0, 70.0))

    bps = sim.get_vehicle_blueprints()
    bp  = (bps.filter("vehicle.carlamotors.carlacola") or bps.filter("vehicle.volkswagen.t2"))[0]
    print("[bp]", bp.id)

    # ── OpenClaw 연동 초기화 ──────────────────────────────────────────────────
    if ENABLE_OPENCLAW:
        _start_trigger_server()   # 18802 수신 대기
        _bridge_reload()          # 브리지 상태 리셋

    platoon = build_platoon(sim, bp, PLATOON_SPAWN)
    platoon[0].controller.waypoints_ahead = compute_lead_route(cmap, platoon[0].get_location())

    coord      = BranchCoordinator(platoon, cmap, sim)
    exit_coord = None
    kb         = KeyInput()
    camera     = SmoothCamera(sim.spectator)
    step   = 0
    _replicator_started  = False

    print("[scenario] 3대 군집 출발  스폰=(%.1f,%.1f)\n" % (
        PLATOON_SPAWN.location.x, PLATOON_SPAWN.location.y))
    if ENABLE_OPENCLAW:
        print("[openclaw] 대기 중 — OpenClaw 에이전트가 협상 후 트리거해야 분기 시작")
        print("[openclaw] 수동 테스트: 키보드 '3' 으로 즉시 트리거 가능\n")

    try:
        while True:
            elapsed = step * DT
            if elapsed > 600.0: break

            key = kb.read()
            if key == "3":
                print("[key] 수동 분기 트리거"); coord.trigger()
            elif key == "r":
                if ENABLE_OPENCLAW: _bridge_reload()
                coord.reset_actors()
                if exit_coord:
                    for v in list(platoon):
                        try: v._carla_vehicle.destroy()
                        except: pass
                platoon = build_platoon(sim, bp, PLATOON_SPAWN)
                platoon[0].controller.waypoints_ahead = compute_lead_route(cmap, platoon[0].get_location())
                coord      = BranchCoordinator(platoon, cmap, sim)
                exit_coord = None
                camera     = SmoothCamera(sim.spectator)
                _branch_trigger_event.clear()
                _replicate_trigger_event.clear()
                _replicator_started = False
                step = 0; continue

            # ── OpenClaw 연동 이벤트 처리 ──────────────────────────────────────
            if ENABLE_OPENCLAW and coord.state == BranchState.CRUISE:
                # (1) OpenClaw가 POST /replicate → 18802/start_replicate → 복제 실행
                if _replicate_trigger_event.is_set() and not _replicator_started:
                    _replicate_trigger_event.clear()
                    _replicator_started = True
                    _start_replicator()
                    print("[openclaw] OpenClaw 명령으로 truck_3 복제 시작")

                # (2) 브리지에서 18802/start_merge 수신 시 분기
                #     (OpenClaw 에이전트가 협상 완료 후 commit → 브리지가 호출)
                if _branch_trigger_event.is_set():
                    _branch_trigger_event.clear()
                    print("[openclaw] 에이전트 협상 완료 → 분기 트리거!")
                    coord.trigger()

            # ── 자동 타이머 fallback (BRANCH_AUTO_S 초 후 트리거) ─────────────
            if BRANCH_AUTO_S > 0 and elapsed >= BRANCH_AUTO_S and coord.state == BranchState.CRUISE:
                print("[auto] %.1fs 자동 분기 트리거" % elapsed); coord.trigger()

            coord.update(step)

            # ── 군집 분기점 이탈 (truck_3 분기 완료 후 2대가 lane=-4 진입) ──────
            if coord.state == BranchState.DONE:
                if exit_coord is None:
                    exit_coord = PlatoonExitCoordinator(platoon, cmap, sim)
                    print("[exit] 군집 분기점 이탈 코디네이터 활성화")
                exit_coord.update()

            sim.run_step(mode="sample" if step % SAMPLING_RATE == 0 else "control")
            sim.tick()
            camera.update(coord.camera_target())

            if step % 100 == 0:
                speeds = ",".join("%.1f" % (v.speed*3.6) for v in platoon)
                gaps   = ",".join("%.1f" % platoon[i].distance_to(platoon[i+1])
                                  for i in range(len(platoon)-1)) or "-"
                exit_s = ("  " + exit_coord.status_line()) if exit_coord else ""
                print("t=%6.1fs  (%s)km/h  gap=(%s)m  %s%s" % (
                    elapsed, speeds, gaps, coord.status_line(), exit_s))
            step += 1
    finally:
        kb.restore(); sim.release_synchronous()

if __name__ == "__main__":
    main()
