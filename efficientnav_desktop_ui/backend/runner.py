from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from .config import ExperimentConfig, RUNS_DIR, save_config
from .result_loader import save_run_result


def build_command(config: ExperimentConfig) -> list[str]:
    script = Path(config.project_root or ".") / config.entry_script
    cmd = [sys.executable, "-u", str(script)]
    if config.run_mode == "planner":
        cmd.append("--planner-only")
    elif config.run_mode == "detection":
        cmd.append("--detection-only")
    elif config.run_mode == "batch":
        cmd.append("--batch")
    return cmd


def start_process(config: ExperimentConfig) -> tuple[subprocess.Popen, Path, Path]:
    config.ensure_run_id()
    config_path = save_config(config)
    log_path = RUNS_DIR / f"{config.run_id}.log"
    env = os.environ.copy()
    env.update(config.to_env())
    env["PYTHONUNBUFFERED"] = "1"
    cwd = Path(config.project_root or ".").resolve()
    cwd.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8", errors="replace")
    process = subprocess.Popen(
        build_command(config),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=str(cwd),
        env=env,
        text=True,
        preexec_fn=os.setsid if os.name != "nt" else None,
    )
    return process, log_path, config_path


def stop_process(process: subprocess.Popen | None):
    if process is None or process.poll() is not None:
        return
    if os.name != "nt":
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    else:
        process.terminate()


def finalize_result(run_id: str, log_path: Path, config_path: Path | None = None) -> Path | None:
    if not log_path.exists():
        return None
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return save_run_result(run_id, text, str(config_path) if config_path else None)
