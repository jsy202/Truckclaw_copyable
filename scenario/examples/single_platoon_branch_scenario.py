"""
Single-Platoon Branch Scenario  —  CARLA 완전 구현
========================================================
3대 단일 군집 주행 중 truck_3 분기 시나리오.
CARLA 설치 시 바로 실행 가능. 없으면 ImportError.

키 입력:
  '3' : truck_3 분기 수동 트리거
  'r' : 시나리오 리셋 (초기 3대 군집으로 복귀)
  Ctrl-C : 종료

터미널 출력:
  - CARLA 물리 상태 (속도, 간격, 상태머신)
  - [vehicle-truck1] / [vehicle-truck3] 컨테이너 목록 (실시간)
"""
from __future__ import annotations

import glob, json, os, select, sys, termios, threading, tty, time
from collections import deque
from enum import Enum, auto
from pathlib import Path

# CARLA 경로
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

_PROJECT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT))
sys.path.insert(0, str(Path(__file__).parent / ".." / "src"))

from PlatooningSimulator import Core, PlatooningControllers
from openclaw_migration.replicator import Replicator
from openclaw_migration.monitor    import ContainerMonitor
from openclaw_migration.reset      import reset as do_reset

# ── 설정 ────────────────────────────────────────────────────────────────────
_CFG_PATH = _PROJECT / "config" / "simulation.json"
def _cfg():
    if _CFG_PATH.exists():
        return json.loads(_CFG_PATH.read_text())
    return {}
_c = _cfg(); _spd = _c.get("speeds",{}); _gap = _c.get("gaps",{}); _sp = _c.get("spawns",{})

DT             = 0.01
SAMPLING_RATE  = 10
PLATOON_SIZE   = 3
PLATOON_SPACING_M   = float(_gap.get("platoon_spacing_m",   18.0))
NORMAL_FOLLOW_GAP_M = float(_gap.get("normal_follow_gap_m", 12.0))
OPEN_GAP_M          = float(_gap.get("open_gap_m",          20.0))
OPEN_GAP_READY_M    = float(_gap.get("open_gap_ready_m",    18.0))
SYNC_SPEED_KMH      = float(_spd.get("sync_speed_kmh",      18.0))
BRANCH_AUTO_S       = 30.0   # 자동 분기 트리거 (초)

_s = _sp.get("p1_spawn", {"x":81.0,"y":136.0,"z":0.3,"pitch":0.0,"yaw":0.2,"roll":0.0})
PLATOON_SPAWN = carla.Transform(
    carla.Location(x=_s["x"], y=_s["y"], z=_s["z"]),
    carla.Rotation(pitch=_s["pitch"], yaw=_s["yaw"], roll=_s["roll"]),
)
BRIDGE_URL = "http://127.0.0.1:18801"

# ── 공통 헬퍼 ───────────────────────────────────────────────────────────────
def _yaw_diff(a, ref): return abs((a - ref + 180.0) % 360.0 - 180.0)
def _straight(cands, yaw): return min(cands, key=lambda w: _yaw_diff(w.transform.rotation.yaw, yaw)) if cands else None
def _retreat(wpt, dist):
    cur, rem = wpt, float(dist)
    while rem > 0:
        step = min(10.0, rem); nxt = cur.previous(step)
        if not nxt: return None
        cur = _straight(nxt, cur.transform.rotation.yaw); rem -= step
    return cur
def _spawn_from_wpt(w):
    t = w.transform
    return carla.Transform(carla.Location(x=t.location.x, y=t.location.y, z=t.location.z+0.3), t.rotation)
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
        cur = _straight(nxt, cur.transform.rotation.yaw); route.append(cur); rem -= step
    return route

# ── 군집 빌드 ────────────────────────────────────────────────────────────────
def build_platoon(sim, bp, spawn, speed, tm, tm_port):
    p = Core.Platoon(sim)
    lead = p.add_lead_vehicle(bp, spawn); sim.tick()
    lead.attach_controller(PlatooningControllers.LeadNavigator(lead, initial_speed=speed))
    anchor = lead; awpt = sim.map.get_waypoint(spawn.location)
    for _ in range(PLATOON_SIZE - 1):
        fwpt = _retreat(awpt, PLATOON_SPACING_M)
        fsp  = _spawn_from_wpt(fwpt) if fwpt else anchor.transform_ahead(-PLATOON_SPACING_M)
        f = p.add_follower_vehicle(bp, fsp); _set_gap(f, NORMAL_FOLLOW_GAP_M)
        f.attach_controller(PlatooningControllers.FollowerController(f, v_ref_cacc, p, dependencies=[-1,0]))
        sim.tick(); anchor = f; awpt = fwpt or awpt
    p.store_follower_waypoints()
    p.lead_waypoints.append(sim.map.get_waypoint(lead.get_location()))
    return p

# ── 상태 머신 ────────────────────────────────────────────────────────────────
class BranchState(Enum):
    CRUISE   = auto()
    GAP_OPEN = auto()
    DETACH   = auto()
    SPAWN_OC = auto()
    DONE     = auto()

class BranchCoordinator:
    def __init__(self, platoon, tm, tm_port, sim):
        self.platoon = platoon; self.tm = tm; self.tm_port = tm_port; self.sim = sim
        self.state = BranchState.CRUISE
        self.triggered = False
        self.branched_v = None
        self._spawn_done = False

    def trigger(self):
        if self.state == BranchState.CRUISE:
            self.triggered = True

    def update(self, step):
        if self.state == BranchState.CRUISE and self.triggered:
            print(f"\n[branch] 목적지 변경 감지 → GAP_OPEN (t={step*DT:.1f}s)")
            _set_gap(self.platoon[2], OPEN_GAP_M)
            self.state = BranchState.GAP_OPEN

        elif self.state == BranchState.GAP_OPEN:
            if len(self.platoon) >= 3:
                gap = self.platoon[1].distance_to(self.platoon[2])
                if gap >= OPEN_GAP_READY_M:
                    print(f"[branch] 간격 {gap:.1f}m 확보 → DETACH")
                    self.state = BranchState.DETACH

        elif self.state == BranchState.DETACH:
            new_p, _ = self.platoon.split(2, 2)
            self.branched_v = new_p[0]
            self.branched_v.set_autopilot(True, self.tm_port)
            print(f"[branch] truck_3 분리 완료 — 단독 autopilot 주행")
            print(f"[branch] 남은 군집: {len(self.platoon)}대")
            self._post_bridge("/reload", {})
            self.state = BranchState.SPAWN_OC

        elif self.state == BranchState.SPAWN_OC and not self._spawn_done:
            self._spawn_done = True
            def _spawn():
                r = Replicator(
                    discord_token=os.environ.get("TRUCK3_DISCORD_BOT_TOKEN",""),
                    gateway_token=os.environ.get("TRUCK3_OPENCLAW_GATEWAY_TOKEN",""),
                    openai_api_key=os.environ.get("OPENAI_API_KEY",""),
                )
                r.replicate()
                self.state = BranchState.DONE
                print("[branch] DONE — OpenClaw 복제 완료")
            threading.Thread(target=_spawn, daemon=True).start()

    def _post_bridge(self, path, body):
        import urllib.request
        try:
            req = urllib.request.Request(
                f"{BRIDGE_URL}{path}",
                data=json.dumps(body).encode(),
                headers={"Content-Type":"application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=1)
        except Exception: pass

    def status_line(self):
        if self.state == BranchState.GAP_OPEN and len(self.platoon) >= 3:
            return f"GAP_OPEN {self.platoon[1].distance_to(self.platoon[2]):.1f}/{OPEN_GAP_READY_M}m"
        return self.state.name

    def reset_carla(self):
        """CARLA actor 제거 후 재스폰"""
        for v in list(self.platoon):
            try: v._carla_vehicle.destroy()
            except Exception: pass
        if self.branched_v:
            try: self.branched_v._carla_vehicle.destroy()
            except Exception: pass
        self.state = BranchState.CRUISE; self.triggered = False
        self.branched_v = None; self._spawn_done = False
        print("[reset] CARLA actor 제거 완료")

# ── 키 입력 ──────────────────────────────────────────────────────────────────
class KeyInput:
    def __init__(self):
        self._active = False
        try:
            self._fd = sys.stdin.fileno(); self._old = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd); self._active = True
            print("[keys] '3'=분기트리거  'r'=리셋  Ctrl-C=종료")
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
        if self._active: termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old); self._active = False

class SmoothCamera:
    def __init__(self, s): self.s=s; self.x=self.y=None
    def update(self, t):
        loc = t.get_location()
        if self.x is None: self.x,self.y=loc.x,loc.y
        self.x+=0.05*(loc.x-self.x); self.y+=0.05*(loc.y-self.y)
        self.s.set_transform(carla.Transform(
            carla.Location(x=self.x,y=self.y,z=loc.z+85), carla.Rotation(pitch=-90)))

# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    # .env 로드
    env_file = _PROJECT / ".env.single-platoon"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip())

    # 컨테이너 모니터 시작
    monitor = ContainerMonitor()

    sim  = Core.Simulation(world="Town06", dt=DT, synchronous=True)
    cmap = sim.map
    bps  = sim.get_vehicle_blueprints()
    bp   = bps.filter("vehicle.carlamotors.european_hgv")[0]
    tm   = sim.get_trafficmanager(); tm.set_synchronous_mode(True); tm_port = tm.get_port()

    platoon = build_platoon(sim, bp, PLATOON_SPAWN, SYNC_SPEED_KMH, tm, tm_port)
    platoon[0].controller.waypoints_ahead = compute_lead_route(cmap, platoon[0].get_location())

    coord  = BranchCoordinator(platoon, tm, tm_port, sim)
    kb     = KeyInput()
    camera = SmoothCamera(sim.spectator)
    step   = 0

    print(f"\n[scenario] 단일 군집 3대 주행 시작")
    print(f"[scenario] 자동 분기: {BRANCH_AUTO_S}초 후\n")

    try:
        while True:
            elapsed = step * DT
            if elapsed > 600.0: break

            key = kb.read()
            if key == "3":
                print(f"\n[key] 수동 분기 트리거 (t={elapsed:.1f}s)")
                coord.trigger()
            elif key == "r":
                print(f"\n[key] 리셋 요청 (t={elapsed:.1f}s)")
                do_reset(carla_coordinator=coord)
                # 재스폰
                platoon = build_platoon(sim, bp, PLATOON_SPAWN, SYNC_SPEED_KMH, tm, tm_port)
                platoon[0].controller.waypoints_ahead = compute_lead_route(cmap, platoon[0].get_location())
                coord = BranchCoordinator(platoon, tm, tm_port, sim)
                step = 0; continue

            # 자동 트리거
            if BRANCH_AUTO_S > 0 and elapsed >= BRANCH_AUTO_S and coord.state == BranchState.CRUISE:
                print(f"\n[auto] t={elapsed:.1f}s 자동 분기 트리거")
                coord.trigger()

            coord.update(step)
            sim.run_step(mode="sample" if step % SAMPLING_RATE == 0 else "control")
            sim.tick()
            camera.update(platoon[0]._carla_vehicle)

            # 100 tick 마다 상태 출력 + 컨테이너 목록
            if step % 100 == 0:
                speeds = ",".join(f"{v.speed*3.6:4.1f}" for v in platoon)
                gaps   = ",".join(f"{platoon[i].distance_to(platoon[i+1]):4.1f}"
                                  for i in range(len(platoon)-1)) or "-"
                print(f"\nt={elapsed:6.1f}s  속도=({speeds}) km/h  간격=({gaps})m  state={coord.status_line()}")
                for line in monitor.display_lines():
                    print(line)

            step += 1
    finally:
        kb.restore()
        sim.release_synchronous()

if __name__ == "__main__":
    main()
