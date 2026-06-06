"""Pure evidence serialization and verdict logic for Split validation."""

from __future__ import annotations

import json
import math
import os
import statistics
from pathlib import Path


TRUCKS = ("truck0", "truck1", "truck2")


def atomic_write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(str(temporary), str(path))


def load_json(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError("missing JSON: {}".format(path))
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError("invalid JSON: {}: {}".format(path, exc))


def _xyz(value):
    return {"x": round(float(value.x), 4), "y": round(float(value.y), 4), "z": round(float(value.z), 4)}


def actor_snapshot(vehicle, cmap):
    actor = vehicle._carla_vehicle
    location = actor.get_location()
    transform = actor.get_transform()
    velocity = actor.get_velocity()
    waypoint = cmap.get_waypoint(location, project_to_road=True)
    speed = 3.6 * math.sqrt(velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2)
    return {
        "actor_id": int(actor.id),
        "type_id": actor.type_id,
        "alive": bool(actor.is_alive),
        "location": _xyz(location),
        "rotation": {
            "pitch": round(float(transform.rotation.pitch), 4),
            "yaw": round(float(transform.rotation.yaw), 4),
            "roll": round(float(transform.rotation.roll), 4),
        },
        "velocity": _xyz(velocity),
        "speed_kmh": round(speed, 4),
        "road_id": int(waypoint.road_id) if waypoint else None,
        "lane_id": int(waypoint.lane_id) if waypoint else None,
    }


def platoon_snapshot(coord, sim, names):
    def name(vehicle):
        return names[id(vehicle)]

    main = list(coord.platoon)
    detached = []
    if getattr(coord, "_v_platoon", None) is not None:
        detached = [v for v in coord._v_platoon if v not in main]
    all_vehicles = {name(v): v for v in list(main) + detached}
    controllers = {}
    for truck, vehicle in all_vehicles.items():
        controller = getattr(vehicle, "controller", None)
        reference = getattr(controller, "platoon", None)
        controllers[truck] = {
            "type": type(controller).__name__ if controller is not None else None,
            "platoon": "main" if reference is coord.platoon or vehicle in main else "detached",
        }
    return {
        "scenario_state": coord.state.name,
        "main_members": [name(v) for v in main],
        "detached_members": [name(v) for v in detached],
        "leader": name(main[0]) if main else None,
        "actors": {truck: actor_snapshot(vehicle, coord.cmap) for truck, vehicle in all_vehicles.items()},
        "controllers": controllers,
        "simulation_platoon_count": len(sim.platoons),
    }


def _first(events, event):
    return next((item for item in events if item.get("event") == event), None)


def evaluate_split(initial, events, final):
    actors_i = initial.get("actors", {})
    actors_f = final.get("actors", {})
    trigger = _first(events, "trigger")
    detach = _first(events, "logical_detach")
    gap = _first(events, "gap_ready")
    lane_event = _first(events, "lane_separated")
    done = _first(events, "done")
    main_lane = {(actors_f.get(n, {}).get("road_id"), actors_f.get(n, {}).get("lane_id")) for n in ("truck0", "truck1")}
    target_lane = (actors_f.get("truck2", {}).get("road_id"), actors_f.get("truck2", {}).get("lane_id"))
    checks = {
        "initial_state": initial.get("scenario_state") == "CRUISE"
        and initial.get("main_members") == list(TRUCKS)
        and set(actors_i) == set(TRUCKS)
        and all(actors_i[n].get("alive") for n in TRUCKS),
        "single_trigger": bool(trigger and trigger.get("accepted"))
        and final.get("trigger_count") == 1
        and sum(1 for e in events if e.get("event") == "trigger" and e.get("accepted")) == 1,
        "logical_detach_observed": bool(detach)
        and detach.get("main_members") == ["truck0", "truck1"]
        and detach.get("detached_members") == ["truck2"],
        "gap_ready": bool(gap) and gap.get("gap_m", -1) >= 15.0 and gap.get("stable_ticks", -1) >= 10,
        "lane_separation": bool(lane_event) and len(main_lane) == 1 and target_lane not in main_lane and None not in target_lane,
        "logical_membership": final.get("main_members") == ["truck0", "truck1"] and final.get("detached_members") == ["truck2"],
        "actors_alive": set(actors_f) == set(TRUCKS) and all(actors_f[n].get("alive") for n in TRUCKS),
        "vehicles_moving": all(actors_f.get(n, {}).get("speed_kmh", 0) > 0 for n in TRUCKS),
        "independent_controller": final.get("controllers", {}).get("truck2", {}).get("type") == "LeadNavigator",
        "independent_motion": final.get("post_done_displacement_m", {}).get("truck2", -1) >= 0.5,
        "collision_free": final.get("collisions") == [],
        "done": final.get("scenario_state") == "DONE" and done is not None,
    }
    reasons = [name for name, passed in checks.items() if not passed]
    timings = {}
    for name, event_name in (
        ("trigger_to_detach_s", "logical_detach"),
        ("trigger_to_gap_ready_s", "gap_ready"),
        ("trigger_to_lane_separated_s", "lane_separated"),
        ("trigger_to_done_s", "done"),
    ):
        event = _first(events, event_name)
        timings[name] = event.get("since_trigger_s") if event else None
    return {"passed": not reasons, "checks": checks, "failure_reasons": reasons, "timings": timings}


def _percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * fraction
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def summarize_results(results):
    values = [r.get("timings", {}).get("trigger_to_done_s") for r in results]
    values = [float(v) for v in values if v is not None]
    timing = {
        "mean": round(statistics.mean(values), 3) if values else None,
        "p50": round(_percentile(values, 0.50), 3) if values else None,
        "p95": round(_percentile(values, 0.95), 3) if values else None,
        "max": round(max(values), 3) if values else None,
    }
    return {
        "runs": len(results),
        "successes": sum(bool(r.get("passed")) for r in results),
        "failures": sum(not bool(r.get("passed")) for r in results),
        "timeouts": sum(bool(r.get("timeout")) for r in results),
        "crashes": sum(bool(r.get("crash")) for r in results),
        "cleanup_failures": sum(bool(r.get("cleanup_failure")) for r in results),
        "timing": timing,
    }
