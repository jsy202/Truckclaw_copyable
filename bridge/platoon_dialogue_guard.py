#!/usr/bin/env python3
"""Discord dialogue guard for TRUCKCLAW platoon negotiation.

The guard is intentionally deterministic. It does not negotiate; it only decides
whether an agent should respond and whether a proposed transfer is consistent
with the destination lists that were actually exchanged in the current chat.
"""

import argparse
import json
import re
import sys


AGENTS = {
    "platoon_a": {
        "name": "TRUCKCLAW2",
        "own_mention": "<@1505082171050688552>",
        "own_display_mention": "@TRUCKCLAW2",
        "peer_mention": "<@1505107885573673041>",
    },
    "platoon_b": {
        "name": "TRUCKCLAW3",
        "own_mention": "<@1505107885573673041>",
        "own_display_mention": "@TRUCKCLAW3",
        "peer_mention": "<@1505082171050688552>",
    },
}

DEST_RE = re.compile(r"\b(platoon_[ab]_truck\d+)\s*:\s*(dest_[A-Za-z0-9_-]+)\b")
REQUEST_ID_RE = re.compile(r"\brequest_id\s*:\s*(tr_[A-Za-z0-9_-]+)\b")
VEHICLE_RE = re.compile(r"\bvehicle_id\s*:\s*(platoon_[ab]_truck\d+)\b")
INLINE_VEHICLE_RE = re.compile(r"\b(platoon_[ab]_truck\d+)\b")
STATUS_RE = re.compile(r"\bstatus\s*:\s*([A-Za-z0-9_-]+)\b")

CONFIRMATION_ONLY_PATTERNS = (
    "확인",
    "대기",
    "동일하게 유지",
    "완료 신호",
    "진행만 대기",
    "상태 유지",
)
ACTION_WORDS = (
    "해줘",
    "확인해",
    "시작",
    "진행",
    "협상",
    "요청",
    "합류가능성",
    "합류 가능성",
    "목적지",
    "request_id",
)


def _load_text(args):
    if args.message is not None:
        return args.message
    if args.message_file:
        with open(args.message_file, "r", encoding="utf-8") as f:
            return f.read()
    return sys.stdin.read()


def _destinations(text):
    return dict(DEST_RE.findall(text or ""))


def _has_machine_update(text):
    return bool(DEST_RE.search(text or "") or REQUEST_ID_RE.search(text or "") or STATUS_RE.search(text or ""))


def _is_confirmation_only(text):
    stripped = re.sub(r"<@\d+>|@\w+", "", text or "").strip()
    if not stripped:
        return True
    if _has_machine_update(stripped):
        return False
    if any(word in stripped for word in ACTION_WORDS):
        return False
    return len(stripped) <= 40 and any(pattern in stripped for pattern in CONFIRMATION_ONLY_PATTERNS)


def _json_out(payload):
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def command_inbound(args):
    text = _load_text(args)
    agent = AGENTS[args.agent]
    if agent["own_mention"] not in text and agent["own_display_mention"] not in text:
        _json_out({
            "allow_response": False,
            "reason": f"missing own mention {agent['own_mention']} or {agent['own_display_mention']}",
        })
        return 1
    if _is_confirmation_only(text):
        _json_out({
            "allow_response": False,
            "reason": "confirmation-only message; prevents acknowledgement loops",
        })
        return 1
    _json_out({"allow_response": True, "reason": "mentioned and contains actionable content"})
    return 0


def _platoon_dest(destinations, platoon_prefix):
    values = [dest for vid, dest in destinations.items() if vid.startswith(platoon_prefix)]
    if not values:
        return None
    return max(set(values), key=values.count)


def _chat_candidate(a_destinations, b_destinations):
    b_dest = _platoon_dest(b_destinations, "platoon_b_")
    a_dest = _platoon_dest(a_destinations, "platoon_a_")
    if not a_dest or not b_dest:
        return []
    return sorted(
        vid for vid, dest in a_destinations.items()
        if vid.startswith("platoon_a_") and not vid.endswith("truck0") and dest == b_dest and dest != a_dest
    )


def command_validate_request(args):
    a_text = args.a_list or ""
    b_text = args.b_list or ""
    request_text = args.request or ""
    if args.a_list_file:
        with open(args.a_list_file, "r", encoding="utf-8") as f:
            a_text = f.read()
    if args.b_list_file:
        with open(args.b_list_file, "r", encoding="utf-8") as f:
            b_text = f.read()
    if args.request_file:
        with open(args.request_file, "r", encoding="utf-8") as f:
            request_text = f.read()

    a_destinations = _destinations(a_text)
    b_destinations = _destinations(b_text)
    candidates = _chat_candidate(a_destinations, b_destinations)

    vehicle = args.vehicle_id
    if not vehicle:
        vehicle_match = VEHICLE_RE.search(request_text) or INLINE_VEHICLE_RE.search(request_text)
        vehicle = vehicle_match.group(1) if vehicle_match else None

    errors = []
    if not a_destinations:
        errors.append("missing current Platoon A destination list from chat")
    if not b_destinations:
        errors.append("missing current Platoon B destination list from chat")
    if not vehicle:
        errors.append("missing requested vehicle_id")
    elif vehicle not in candidates:
        errors.append(f"{vehicle} is not destination-compatible from the current chat lists")

    if len(candidates) > 1:
        errors.append(f"ambiguous chat candidates: {', '.join(candidates)}")

    _json_out({
        "valid": not errors,
        "vehicle_id": vehicle,
        "chat_candidates": candidates,
        "platoon_a_destinations": a_destinations,
        "platoon_b_destinations": b_destinations,
        "errors": errors,
    })
    return 0 if not errors else 2


def _load_destinations_config(args, context):
    path = args.destinations_file or context.get("destination_file")
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _vehicle_destinations(destinations_config, platoon_id):
    vehicles = destinations_config.get("vehicles", {})
    return {
        vehicle_id: vehicle.get("destination_id")
        for vehicle_id, vehicle in vehicles.items()
        if vehicle.get("platoon_id") == platoon_id
    }


def _platoon_destination(destinations_config, platoon_id):
    return destinations_config.get("platoons", {}).get(platoon_id, {}).get("destination_id")


def command_validate_json(args):
    with open(args.context_file, "r", encoding="utf-8") as f:
        context = json.load(f)

    destinations_config = _load_destinations_config(args, context)
    if args.agent == "platoon_a":
        source_platoon_id = context.get("own_platoon", {}).get("platoon_id", "platoon_a")
        target_platoon_id = context.get("peer_platoon", {}).get("platoon_id", "platoon_b")
    else:
        source_platoon_id = context.get("peer_platoon", {}).get("platoon_id", "platoon_a")
        target_platoon_id = context.get("own_platoon", {}).get("platoon_id", "platoon_b")

    source_destinations = _vehicle_destinations(destinations_config, source_platoon_id)
    source_platoon_dest = _platoon_destination(destinations_config, source_platoon_id)
    target_platoon_dest = _platoon_destination(destinations_config, target_platoon_id)

    candidates = sorted(
        vehicle_id for vehicle_id, destination_id in source_destinations.items()
        if vehicle_id.startswith("platoon_a_")
        and not vehicle_id.endswith("truck0")
        and destination_id == target_platoon_dest
        and destination_id != source_platoon_dest
    )

    errors = []
    if not destinations_config:
        errors.append("missing destination file")
    if not source_destinations:
        errors.append("missing source vehicle destinations in destination file")
    if not source_platoon_dest:
        errors.append("missing source platoon destination in destination file")
    if not target_platoon_dest:
        errors.append("missing target platoon destination in destination file")
    if args.vehicle_id not in candidates:
        errors.append(f"{args.vehicle_id} is not destination-compatible from destination file")
    if len(candidates) > 1:
        errors.append(f"ambiguous JSON candidates: {', '.join(candidates)}")

    _json_out({
        "valid": not errors,
        "vehicle_id": args.vehicle_id,
        "json_candidates": candidates,
        "destination_file": args.destinations_file or context.get("destination_file"),
        "source_platoon_destination": source_platoon_dest,
        "target_platoon_destination": target_platoon_dest,
        "source_destinations": source_destinations,
        "errors": errors,
    })
    return 0 if not errors else 2


def build_parser():
    parser = argparse.ArgumentParser(description="Guard Discord TRUCKCLAW negotiation turns.")
    sub = parser.add_subparsers(dest="command", required=True)

    inbound = sub.add_parser("inbound")
    inbound.add_argument("--agent", choices=AGENTS.keys(), required=True)
    inbound.add_argument("--message")
    inbound.add_argument("--message-file")

    validate = sub.add_parser("validate-request")
    validate.add_argument("--a-list")
    validate.add_argument("--a-list-file")
    validate.add_argument("--b-list")
    validate.add_argument("--b-list-file")
    validate.add_argument("--request")
    validate.add_argument("--request-file")
    validate.add_argument("--vehicle-id")

    validate_json = sub.add_parser("validate-json")
    validate_json.add_argument("--agent", choices=AGENTS.keys(), required=True)
    validate_json.add_argument("--context-file", required=True)
    validate_json.add_argument("--destinations-file")
    validate_json.add_argument("--vehicle-id", required=True)

    return parser


def main():
    args = build_parser().parse_args()
    if args.command == "inbound":
        return command_inbound(args)
    if args.command == "validate-request":
        return command_validate_request(args)
    if args.command == "validate-json":
        return command_validate_json(args)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
