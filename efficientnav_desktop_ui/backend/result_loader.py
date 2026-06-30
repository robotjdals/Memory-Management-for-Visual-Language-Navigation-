from __future__ import annotations

import json
import re
from pathlib import Path
from .config import RESULTS_DIR
from .house_browser import summarize_houses
from .log_parser import parse_log_text

_HOUSE_SUMMARY_CACHE: dict[tuple[int, int], list] = {}


def parse_metrics_from_text(text: str) -> dict:
    result = {
        "sr": None,
        "spl": None,
        "final_length": None,
        "trajectory_length": None,
        "episode_time": None,
        "planning_time_total": None,
        "planning_time_avg": None,
        "planning_calls": 0,
        "h2o_evictions": 0,
        "h2o_avg_seq_before": None,
        "h2o_avg_seq_after": None,
        "success": None,
        "fail_reason": "",
    }
    patterns = {
        "sr": r"\bsr\s*[:=]\s*([0-9.]+)",
        "spl": r"\bspl\s*[:=]\s*([0-9.]+)",
        "final_length": r"\bfinal_length\s*[:=]\s*([0-9.]+)",
        "trajectory_length": r"\btrajectory_length\s*[:=]\s*([0-9.]+)",
    }
    for key, pattern in patterns.items():
        matches = re.findall(pattern, text, re.I)
        if matches:
            try:
                result[key] = float(matches[-1])
            except ValueError:
                pass
    episode_times = re.findall(r"\bepisode elapsed\s*=\s*([0-9.]+)s", text, re.I)
    if episode_times:
        result["episode_time"] = float(episode_times[-1])

    planning_times = [float(value) for value in re.findall(r"\bplanning mode=.*?elapsed=([0-9.]+)s", text, re.I)]
    result["planning_calls"] = len(planning_times)
    if planning_times:
        result["planning_time_total"] = sum(planning_times)
        result["planning_time_avg"] = sum(planning_times) / len(planning_times)

    h2o_events = re.findall(r"H2O cache eviction:.*?seq_before=(\d+).*?seq_after=(\d+)", text, re.I)
    result["h2o_evictions"] = len(h2o_events)
    if h2o_events:
        seq_before = [int(before) for before, _ in h2o_events]
        seq_after = [int(after) for _, after in h2o_events]
        result["h2o_avg_seq_before"] = sum(seq_before) / len(seq_before)
        result["h2o_avg_seq_after"] = sum(seq_after) / len(seq_after)
    summary = parse_log_text(text)
    result["success"] = summary.success
    result["fail_reason"] = summary.fail_reason
    return result


def save_run_result(run_id: str, log_text: str, config_path: str | None = None) -> Path:
    metrics = parse_metrics_from_text(log_text)
    metadata = load_result_metadata(config_path)
    payload = {
        "run_id": run_id,
        "config_path": config_path,
        **metrics,
        "tl": metrics.get("trajectory_length")
        if metrics.get("trajectory_length") is not None
        else metrics.get("final_length"),
        **metadata,
    }
    path = RESULTS_DIR / f"{run_id}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_result_metadata(config_path: str | None) -> dict:
    metadata = {
        "target_object": "",
        "house_index": "",
        "house_size": "",
        "h2o_condition": "",
        "use_kv_cache": None,
        "comparison_condition": "",
        "batch_id": "",
        "batch_order": 0,
    }
    if not config_path:
        return metadata
    try:
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except Exception:
        return metadata
    target = config.get("effective_target") or config.get("custom_target_object") or config.get("target_object") or ""
    house_index = config.get("house_index", "")
    seed = int(config.get("seed", 7))
    h2o_config = config.get("h2o") or {}
    use_kv_cache = bool(config.get("use_kv_cache", True))
    metadata["target_object"] = target
    metadata["house_index"] = house_index
    metadata["batch_id"] = config.get("batch_id", "")
    metadata["batch_order"] = config.get("batch_order", 0)
    metadata["use_kv_cache"] = use_kv_cache
    if h2o_config.get("enabled"):
        metadata["h2o_condition"] = f"on/{h2o_config.get('budget')}"
    else:
        metadata["h2o_condition"] = "off"
    if not use_kv_cache:
        metadata["comparison_condition"] = "base"
    elif h2o_config.get("enabled"):
        metadata["comparison_condition"] = f"base+kv+h2o/{h2o_config.get('budget')}"
    else:
        metadata["comparison_condition"] = "base+kv"
    try:
        required_limit = int(house_index) + 1
        cache_key = (seed, max(required_limit, 100))
        if cache_key not in _HOUSE_SUMMARY_CACHE:
            _HOUSE_SUMMARY_CACHE[cache_key] = summarize_houses(seed=seed, limit=cache_key[1])
        summaries = _HOUSE_SUMMARY_CACHE[cache_key]
        if 0 <= int(house_index) < len(summaries):
            metadata["house_size"] = summaries[int(house_index)].size
    except Exception:
        metadata["house_size"] = ""
    return metadata


def _batch_sort_key(path: Path, row: dict) -> tuple:
    batch_id = str(row.get("batch_id") or "")
    if batch_id:
        batch_rank_text = re.sub(r"\D", "", batch_id)
        batch_rank = int(batch_rank_text) if batch_rank_text else 0
        try:
            batch_order = int(row.get("batch_order") or 0)
        except (TypeError, ValueError):
            batch_order = 0
        return (-batch_rank, batch_order, str(row.get("run_id") or ""))
    try:
        fallback_rank = int(path.stat().st_mtime_ns)
    except OSError:
        fallback_rank = 0
    return (-fallback_rank, 0, str(row.get("run_id") or ""))


def load_recent_results(limit: int = 50) -> list[dict]:
    rows_with_path = []
    for path in RESULTS_DIR.glob("*.json"):
        try:
            rows_with_path.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    rows_with_path.sort(key=lambda item: _batch_sort_key(item[0], item[1]))
    return [row for _, row in rows_with_path[:limit]]
