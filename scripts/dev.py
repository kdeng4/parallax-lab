#!/usr/bin/env python3
"""Run both development services, forwarding signals to their process groups."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
processes: list[subprocess.Popen] = []


def stop(*_args: object) -> None:
    for process in processes:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def main() -> int:
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_args: sys.exit(0))
    try:
        processes.append(subprocess.Popen(
            ['uv', 'run', '--frozen', 'uvicorn', 'parallax_lab.main:app',
             '--host', '127.0.0.1', '--port', '8000', '--reload'],
            cwd=ROOT / 'apps/api', start_new_session=True,
        ))
        processes.append(subprocess.Popen(
            ['npm', 'run', 'dev', '--', '--hostname', '127.0.0.1', '--port', '3000'],
            cwd=ROOT / 'apps/web', start_new_session=True,
            env={**os.environ, 'PARALLAX_LOCAL_WRITE_ACCESS': '1'},
        ))
        print('Parallax Lab: frontend port 3000 · API port 8000 · paper / synthetic only', flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        return next((p.returncode for p in processes if p.returncode is not None), 1)
    finally:
        stop()


if __name__ == '__main__':
    sys.exit(main())
