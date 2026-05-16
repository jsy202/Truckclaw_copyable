#!/usr/bin/env python3
"""
ContainerMonitor — 터미널 실시간 컨테이너 모니터
vehicle-truck1, vehicle-truck3 안의 openclaw 컨테이너 상태를 1초마다 폴링
"""
from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class ContainerInfo:
    name: str
    status: str

    @property
    def is_running(self) -> bool:
        return "Up" in self.status

    @property
    def icon(self) -> str:
        if "Up" in self.status:
            return "✓"
        if "starting" in self.status.lower() or "created" in self.status.lower():
            return "↺"
        return "✗"

    def __str__(self) -> str:
        short = self.status[:25] if len(self.status) > 25 else self.status
        return f"{self.name}: {short} {self.icon}"


class ContainerMonitor:
    """
    백그라운드 스레드로 docker ps를 폴링하여
    각 vehicle의 컨테이너 상태를 실시간으로 유지한다.
    """

    TRUCK_IDS = ["truck1", "truck3"]

    def __init__(self, poll_interval: float = 1.0) -> None:
        self._poll_interval = poll_interval
        self._status: dict[str, List[ContainerInfo]] = {t: [] for t in self.TRUCK_IDS}
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def _query_containers(self, truck_id: str) -> List[ContainerInfo]:
        try:
            result = subprocess.run(
                [
                    "docker", "ps", "-a",
                    "--filter", f"name={truck_id}",
                    "--format", "{{.Names}}\t{{.Status}}",
                ],
                capture_output=True, text=True, timeout=2,
            )
            containers = []
            for line in result.stdout.strip().splitlines():
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    containers.append(ContainerInfo(name=parts[0], status=parts[1]))
            return containers
        except Exception:
            return []

    def _poll_loop(self) -> None:
        while True:
            for truck_id in self.TRUCK_IDS:
                containers = self._query_containers(truck_id)
                with self._lock:
                    self._status[truck_id] = containers
            time.sleep(self._poll_interval)

    def snapshot(self) -> dict[str, List[ContainerInfo]]:
        with self._lock:
            return {k: list(v) for k, v in self._status.items()}

    def display_lines(self) -> List[str]:
        """터미널 출력용 라인 목록 반환"""
        snap = self.snapshot()
        lines = []
        for truck_id in self.TRUCK_IDS:
            containers = snap[truck_id]
            if containers:
                for c in containers:
                    lines.append(f"  [vehicle-{truck_id}]  {c}")
            else:
                lines.append(f"  [vehicle-{truck_id}]  (컨테이너 없음)")
        return lines

    def print_status(self) -> None:
        for line in self.display_lines():
            print(line)


if __name__ == "__main__":
    print("컨테이너 모니터 시작 (Ctrl-C로 종료)")
    monitor = ContainerMonitor()
    try:
        while True:
            print("\033[2J\033[H", end="")  # 화면 클리어
            print("─" * 50)
            monitor.print_status()
            print("─" * 50)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
