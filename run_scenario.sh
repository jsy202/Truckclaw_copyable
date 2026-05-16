#!/bin/bash
# CARLA 시나리오 실행 스크립트 (no-rendering Docker 환경용)
cd /home/jsy/Truckclaw-improve

# CARLA PythonAPI 경로 자동 탐색
for path in \
    /opt/carla-0.9.6/PythonAPI/carla \
    /opt/carla-simulator/PythonAPI/carla \
    /opt/carla/PythonAPI/carla \
    ~/carla/PythonAPI/carla; do
    if [ -d "$path" ]; then
        export PYTHONPATH=$PYTHONPATH:$path
        echo "[run] CARLA PythonAPI: $path"
        break
    fi
done

# egg 파일 자동 탐색
EGG=$(find /opt -name "carla-*.egg" 2>/dev/null | head -1)
if [ -n "$EGG" ]; then
    export PYTHONPATH=$PYTHONPATH:$(dirname $EGG)
    echo "[run] CARLA egg: $EGG"
fi

# 브리지 서버 실행 (없으면)
if ! curl -s http://127.0.0.1:18801/health > /dev/null 2>&1; then
    echo "[run] 브리지 서버 시작..."
    python3 bridge/platoon_bridge_server.py &
    sleep 2
fi

echo "[run] 시나리오 시작..."
python3 scenario/examples/single_platoon_branch_scenario.py
