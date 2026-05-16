#!/bin/bash
# ============================================================
#  run_truckclaw.sh — Truckclaw 시나리오 원클릭 실행
#  OpenClaw 연동 포함:
#    브리지 서버(18801) + Docker 컨테이너(truck1) + 시나리오
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CARLA_PORT=2000
BRIDGE_PORT=18801
TRIGGER_PORT=18802
PYAPI="/opt/carla-0.9.6/PythonAPI/carla/dist/carla-0.9.6-py3.5-linux-x86_64.egg"
PYAPI_DIR="/opt/carla-0.9.6/PythonAPI/carla"
ENV_FILE="$SCRIPT_DIR/.env.single-platoon"

GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
log()  { echo -e "${CYAN}[truckclaw]${NC} $1"; }
ok()   { echo -e "${GREEN}[truckclaw] ✓${NC} $1"; }
warn() { echo -e "${YELLOW}[truckclaw] !${NC} $1"; }
err()  { echo -e "${RED}[truckclaw] ✗${NC} $1"; exit 1; }

cd "$SCRIPT_DIR"

# 1. CARLA 서버 확인
log "CARLA 서버 확인 중 (포트 $CARLA_PORT)..."
if ! ss -tlnp | grep -q ":$CARLA_PORT"; then
    warn "CARLA 서버가 실행 중이 아닙니다 → 자동 시작"
    bash "$SCRIPT_DIR/carla_start.sh" || err "CARLA 시작 실패"
else
    ok "CARLA 서버 실행 중"
fi

# 2. PYTHONPATH 설정
export PYTHONPATH="$PYAPI:$PYAPI_DIR:$SCRIPT_DIR/scenario/src:$SCRIPT_DIR/openclaw_migration:$PYTHONPATH"
log "PYTHONPATH 설정 완료"

# 3. 브리지 서버 확인 / 시작
log "브리지 서버 확인 중 (포트 $BRIDGE_PORT)..."
if curl -s http://127.0.0.1:$BRIDGE_PORT/health &>/dev/null; then
    ok "브리지 서버 실행 중"
else
    log "브리지 서버 시작 중..."
    python3.7 "$SCRIPT_DIR/bridge/platoon_bridge_server.py" &
    BRIDGE_PID=$!
    sleep 2
    if curl -s http://127.0.0.1:$BRIDGE_PORT/health &>/dev/null; then
        ok "브리지 서버 시작됨 (PID=$BRIDGE_PID)"
    else
        warn "브리지 서버 시작 실패 — OpenClaw 없이 진행"
    fi
fi

# 4. Docker 상태 표시
echo ""
echo -e "${BOLD}── Docker 상태 ─────────────────────────────────${NC}"
if ! command -v docker &>/dev/null; then
    echo -e "  ${RED}✗${NC} Docker 미설치"
elif ! docker info &>/dev/null 2>&1; then
    echo -e "  ${RED}✗${NC} Docker 데몬 응답 없음"
else
    # 전체 컨테이너 목록 (truckclaw 관련)
    CONTAINERS=$(docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" \
        --filter "name=vehicle-truck" \
        --filter "name=openclaw" \
        --filter "name=sp-bridge" 2>/dev/null)

    if [ -z "$(echo "$CONTAINERS" | tail -n +2)" ]; then
        echo -e "  ${YELLOW}!${NC} Truckclaw 관련 컨테이너 없음"
    else
        echo "$CONTAINERS" | while IFS= read -r line; do
            if echo "$line" | grep -qE "^NAME|NAMES"; then
                echo -e "  ${BOLD}$(echo "$line")${NC}"
            elif echo "$line" | grep -qiE "up|running"; then
                echo -e "  ${GREEN}▶${NC} $line"
            elif echo "$line" | grep -qiE "exited|dead"; then
                echo -e "  ${RED}■${NC} $line"
            else
                echo -e "  ${YELLOW}○${NC} $line"
            fi
        done
    fi

    # openclaw-truck3 별도 표시 (분기 후 동적 생성)
    TRUCK3=$(docker ps -a --format "  {{.Names}}  {{.Status}}" \
        --filter "name=openclaw-truck3" 2>/dev/null)
    if [ -n "$TRUCK3" ]; then
        echo -e "  ${CYAN}[truck3]${NC}$TRUCK3"
    fi

    # .env 없으면 안내
    if [ ! -f "$ENV_FILE" ]; then
        echo -e "  ${YELLOW}!${NC} .env.single-platoon 없음 → 컨테이너 자동시작 스킵"
        echo -e "     생성: ${CYAN}cp .env.example .env.single-platoon${NC} 후 토큰 설정"
    else
        # vehicle-truck1 실행 중 아니면 자동 시작
        if docker ps --format '{{.Names}}' | grep -q "^vehicle-truck1$"; then
            ok "vehicle-truck1 실행 중"
        else
            log "vehicle-truck1 시작 중..."
            docker compose -f "$SCRIPT_DIR/docker-compose.single-platoon.yml" \
                --env-file "$ENV_FILE" \
                up -d vehicle-truck1 2>/dev/null && \
                ok "vehicle-truck1 시작됨" || \
                warn "vehicle-truck1 시작 실패 — OpenClaw 없이 진행"
        fi
    fi
fi
echo -e "${BOLD}────────────────────────────────────────────────${NC}"

# 5. 시나리오 실행
echo ""
echo -e "${BOLD}════════════════════════════════════════════${NC}"
ok "Truckclaw 시나리오 시작!"
echo -e "  키:  ${BOLD}'3'${NC}=분기트리거  ${BOLD}'r'${NC}=리셋  ${BOLD}Ctrl-C${NC}=종료"
echo -e "  브리지: ${CYAN}http://127.0.0.1:$BRIDGE_PORT/snapshot${NC}"
echo -e "  트리거: POST http://127.0.0.1:$TRIGGER_PORT/start_merge"
echo -e "${BOLD}════════════════════════════════════════════${NC}"
echo ""
python3.7 "$SCRIPT_DIR/scenario/examples/single_platoon_branch_scenario.py"
