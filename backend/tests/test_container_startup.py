"""用替身进程验证镜像实际启动命令的迁移、退出与信号处理。"""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest


@pytest.mark.parametrize("scenario", ["migration", "backend", "frontend", "terminate"])
def test_container_startup(tmp_path, scenario):
    root = Path(__file__).resolve().parents[2]
    command = next(
        line.removeprefix("CMD ")
        for line in (root / "Dockerfile").read_text().splitlines()
        if line.startswith("CMD ")
    )
    (tmp_path / "frontend").mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = f"""#!{sys.executable}
import os, pathlib, signal, sys, time
name = 'frontend' if pathlib.Path(sys.argv[0]).name == 'node' else ('migration' if 'migrate' in sys.argv else 'backend')
directory = pathlib.Path(os.environ['STARTUP_TEST_DIR'])
def stop(signum, frame):
    (directory / (name + '.stopped')).touch()
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
(directory / (name + '.started')).touch()
if name == 'migration':
    sys.exit(1 if os.environ['STARTUP_TEST_SCENARIO'] == name else 0)
if os.environ['STARTUP_TEST_SCENARIO'] == name:
    time.sleep(0.2)
    sys.exit(7)
time.sleep(60)
"""
    for name in ("python3", "node"):
        executable = bin_dir / name
        executable.write_text(stub)
        executable.chmod(0o755)

    process = subprocess.Popen(
        json.loads(command),
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "STARTUP_TEST_DIR": str(tmp_path),
            "STARTUP_TEST_SCENARIO": scenario,
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        if scenario == "terminate":
            deadline = time.monotonic() + 5
            while not all((tmp_path / f"{name}.started").exists() for name in ("backend", "frontend")):
                assert process.poll() is None, "启动命令在服务启动前退出"
                assert time.monotonic() < deadline, "服务启动超时"
                time.sleep(0.01)
            process.terminate()
        _, stderr = process.communicate(timeout=5)
        assert b"Illegal option" not in stderr
        assert process.returncode == (0 if scenario == "terminate" else 1)
        assert (tmp_path / "migration.started").exists()
        if scenario == "migration":
            assert not (tmp_path / "backend.started").exists()
            assert not (tmp_path / "frontend.started").exists()
        else:
            for name in ("backend", "frontend"):
                assert (tmp_path / f"{name}.started").exists()
                if name != scenario:
                    assert (tmp_path / f"{name}.stopped").exists()
    finally:
        # 失败路径也清理整组替身进程，避免测试残留。
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
