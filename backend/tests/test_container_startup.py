"""用替身进程验证容器启动脚本的迁移、退出与信号处理。"""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest


@pytest.mark.parametrize("scenario", ["nginx_config", "migration", "backend", "frontend", "nginx", "terminate"])
def test_container_startup(tmp_path, scenario):
    root = Path(__file__).resolve().parents[2]
    entrypoint = next(
        line.removeprefix("ENTRYPOINT ")
        for line in (root / "Dockerfile").read_text().splitlines()
        if line.startswith("ENTRYPOINT ")
    )
    command = json.loads(entrypoint)
    assert command == ["/bin/sh", "/app/start.sh"]
    script = tmp_path / "start.sh"
    script.write_bytes((root / "docker/start.sh").read_bytes())
    command[1] = str(script)
    (tmp_path / "frontend").mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = f"""#!{sys.executable}
import os, pathlib, signal, sys, time
executable = pathlib.Path(sys.argv[0]).name
if executable == 'nginx':
    name = 'nginx_config' if '-t' in sys.argv else 'nginx'
elif executable == 'node':
    name = 'frontend'
    assert os.environ['HOSTNAME'] == '127.0.0.1'
    assert os.environ['PORT'] == '3001'
else:
    name = 'migration' if 'migrate' in sys.argv else 'backend'
directory = pathlib.Path(os.environ['STARTUP_TEST_DIR'])
def stop(signum, frame):
    (directory / (name + '.stopped')).touch()
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
(directory / (name + '.started')).touch()
if name in ('migration', 'nginx_config'):
    sys.exit(1 if os.environ['STARTUP_TEST_SCENARIO'] == name else 0)
if os.environ['STARTUP_TEST_SCENARIO'] == name:
    time.sleep(0.2)
    sys.exit(7)
time.sleep(60)
"""
    for name in ("python3", "node", "nginx"):
        executable = bin_dir / name
        executable.write_text(stub)
        executable.chmod(0o755)

    process = subprocess.Popen(
        command,
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
            while not all((tmp_path / f"{name}.started").exists() for name in ("backend", "frontend", "nginx")):
                assert process.poll() is None, "启动命令在服务启动前退出"
                assert time.monotonic() < deadline, "服务启动超时"
                time.sleep(0.01)
            process.terminate()
        _, stderr = process.communicate(timeout=5)
        assert b"Illegal option" not in stderr
        assert process.returncode == (0 if scenario == "terminate" else 1)
        assert (tmp_path / "nginx_config.started").exists()
        if scenario == "nginx_config":
            assert not (tmp_path / "migration.started").exists()
        else:
            assert (tmp_path / "migration.started").exists()
        if scenario in ("nginx_config", "migration"):
            for name in ("backend", "frontend", "nginx"):
                assert not (tmp_path / f"{name}.started").exists()
        else:
            for name in ("backend", "frontend", "nginx"):
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
