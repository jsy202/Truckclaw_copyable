#!/bin/bash
# vehicle 컨테이너 시작 스크립트
# Docker 소켓 공유로 내부에서 openclaw 컨테이너를 실행함

TRUCK_ID=${TRUCK_ID:-truck1}
OPENCLAW_CONTAINER="openclaw-${TRUCK_ID}"
OPENCLAW_DATA_DIR=${OPENCLAW_DATA_DIR:-/data/openclaw}
# 호스트 경로를 우선 사용 (DinD 환경 대응)
OPENCLAW_HOST_DATA_DIR=${OPENCLAW_HOST_DATA_DIR:-${OPENCLAW_DATA_DIR}}

echo "[vehicle-${TRUCK_ID}] 시작 중..."
echo "[vehicle-${TRUCK_ID}] Host Data Dir: ${OPENCLAW_HOST_DATA_DIR}"

# 기존에 같은 이름의 컨테이너가 있으면 제거
docker rm -f ${OPENCLAW_CONTAINER} 2>/dev/null || true

# openclaw 컨테이너 실행 (대기 상태로 시작)
# ENTRYPOINT가 ["bash", "-lc"] 이므로 명령어를 하나로 묶어 전달해야 함
docker run -d \
  --name ${OPENCLAW_CONTAINER} \
  --network host \
  -e HOME=/data/openclaw \
  -e DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN} \
  -e OPENCLAW_GATEWAY_TOKEN=${OPENCLAW_GATEWAY_TOKEN} \
  -e OPENAI_API_KEY=${OPENAI_API_KEY:-} \
  -v ${OPENCLAW_HOST_DATA_DIR}:/data/openclaw \
  -v ${HOST_PROJECT_ROOT}/bridge:/project/scripts:ro \
  openclaw:local \
  "sleep infinity"

echo "[vehicle-${TRUCK_ID}] ${OPENCLAW_CONTAINER} 컨테이너 시작됨"

# 약간의 대기 (컨테이너 내부 초기화 시간)
sleep 2

# 내부에서 모델 설정 및 게이트웨이 구동
echo "[vehicle-${TRUCK_ID}] 모델 설정 중..."
docker exec ${OPENCLAW_CONTAINER} bash -lc "openclaw models set openai-codex/gpt-5.4" || true

echo "[vehicle-${TRUCK_ID}] 게이트웨이 실행 중..."
docker exec -d ${OPENCLAW_CONTAINER} bash -lc "openclaw gateway run --port 18790 --allow-unconfigured"

# 컨테이너 살아있게 유지
tail -f /dev/null
