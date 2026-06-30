from __future__ import annotations

import html
import re
import ast
from dataclasses import dataclass
from pathlib import Path

HIGHLIGHTS = [
    ("SUCCESS", re.compile(r"episode success|final goal visible|close enough", re.I), "#d7ffd9"),
    ("FAIL", re.compile(r"episode failed|failed|not found|found_path=False|timeout|rejected", re.I), "#ffd7d7"),
    ("PLANNER", re.compile(r"allowed planner objects|Place summaries|planner selected|raw planner|sanitized", re.I), "#d8e8ff"),
    ("DETECTION", re.compile(r"detect|bbox|semantic goal candidate|RGB detector|box_match|visible_ratio", re.I), "#f0dcff"),
    ("H2O", re.compile(r"H2O|eviction|heavy|protected_prefix|cache|trim", re.I), "#dcfff3"),
]

@dataclass
class LogSummary:
    success: bool | None = None
    fail_reason: str = ""
    final_goal_visible: bool = False
    planner_events: int = 0
    detection_events: int = 0
    h2o_events: int = 0
    highlighted_lines: list[str] = None


def classify_line(line: str):
    labels = []
    colors = []
    for label, pattern, color in HIGHLIGHTS:
        if pattern.search(line):
            labels.append(label)
            colors.append(color)
    return labels, colors


def line_to_html(line: str) -> str:
    labels, colors = classify_line(line)
    safe = html.escape(line.rstrip())
    if not labels:
        return f"<div style='font-family:monospace; white-space:pre-wrap'>{safe}</div>"
    color = colors[0]
    tag = "/".join(labels)
    return f"<div style='font-family:monospace; white-space:pre-wrap; background:{color}; padding:2px 4px'><b>[{tag}]</b> {safe}</div>"


def parse_log_text(text: str) -> LogSummary:
    summary = LogSummary(highlighted_lines=[])
    for raw in text.splitlines():
        line = raw.strip()
        labels, _ = classify_line(line)
        if labels:
            summary.highlighted_lines.append(line)
        low = line.lower()
        if "episode success" in low:
            summary.success = True
            summary.fail_reason = ""
        if "episode failed" in low:
            summary.success = False
            summary.fail_reason = summary.fail_reason or "episode failed"
        if "final goal visible" in low:
            summary.final_goal_visible = True
        if "not found in current house" in low:
            summary.success = False
            summary.fail_reason = "goal not in house"
        elif "found_path=false" in low:
            summary.success = False
            summary.fail_reason = "no path"
        elif "semantic goal candidate rejected" in low:
            if summary.success is not True:
                summary.fail_reason = summary.fail_reason or "RGB detector failed or semantic mismatch"
        elif "timed out waiting for detection service" in low:
            summary.success = False
            summary.fail_reason = "detection timeout"
        if "PLANNER" in labels:
            summary.planner_events += 1
        if "DETECTION" in labels:
            summary.detection_events += 1
        if "H2O" in labels:
            summary.h2o_events += 1
    return summary


def _parse_debug_dict(line: str) -> dict:
    try:
        _, payload = line.split(":", 1)
        value = ast.literal_eval(payload.strip())
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _extract_summary_field(summary: str, field: str) -> str:
    match = re.search(rf"{re.escape(field)}=(.*?)(?:\.\s+[a-z_]+=|\.\s*$)", summary)
    if not match:
        return ""
    return match.group(1).strip()


def parse_place_rows(text: str) -> list[dict[str, str]]:
    places: dict[int, dict[str, str]] = {}
    allowed_by_place: dict = {}
    selected_place = ""
    selected_angle = ""
    selected_objects = ""

    summary_pattern = re.compile(
        r"Place\s+(\d+)\s+summary:\s+(.*?)(?=\s+\{|\s+Place\s+\d+\s+summary:|$)"
    )
    selected_pattern = re.compile(
        r"planner selected:\s*place=([^,]+),\s*angle=([^,]+),\s*objects=(.*)$",
        re.I,
    )

    for raw in text.splitlines():
        line = raw.strip()
        if "allowed planner objects by place:" in line:
            allowed_by_place = _parse_debug_dict(line)
            continue

        selected_match = selected_pattern.search(line)
        if selected_match:
            selected_place = selected_match.group(1).strip()
            selected_angle = selected_match.group(2).strip()
            selected_objects = selected_match.group(3).strip()
            continue

        for match in summary_pattern.finditer(line):
            place_id = int(match.group(1))
            summary = match.group(2).strip()
            places[place_id] = {
                "place": str(place_id),
                "salient": _extract_summary_field(summary, "salient"),
                "frontier": _extract_summary_field(summary, "frontier"),
                "goal_like": _extract_summary_field(summary, "goal_like"),
                "observations": _extract_summary_field(summary, "observations"),
                "allowed": "",
                "selected": "",
            }

    for place_id, labels in allowed_by_place.items():
        try:
            normalized_place_id = int(place_id)
        except Exception:
            continue
        row = places.setdefault(
            normalized_place_id,
            {
                "place": str(normalized_place_id),
                "salient": "",
                "frontier": "",
                "goal_like": "",
                "observations": "",
                "allowed": "",
                "selected": "",
            },
        )
        if isinstance(labels, (list, tuple)):
            row["allowed"] = ", ".join(str(label) for label in labels)
        else:
            row["allowed"] = str(labels)

    if selected_place != "":
        try:
            normalized_selected_place = int(selected_place)
        except Exception:
            normalized_selected_place = None
        if normalized_selected_place is not None:
            row = places.setdefault(
                normalized_selected_place,
                {
                    "place": str(normalized_selected_place),
                    "salient": "",
                    "frontier": "",
                    "goal_like": "",
                    "observations": "",
                    "allowed": "",
                    "selected": "",
                },
            )
            row["selected"] = f"angle={selected_angle} objects={selected_objects}"

    return [places[key] for key in sorted(places)]


def parse_place_memory_text(text: str) -> str:
    rows = parse_place_rows(text)
    if not rows:
        return "아직 저장된 place memory가 없습니다."

    blocks = []
    for row in rows:
        lines = [f"Place {row.get('place', '')}"]
        salient = row.get("salient", "")
        frontier = row.get("frontier", "")
        goal_like = row.get("goal_like", "")
        observations = row.get("observations", "")
        allowed = row.get("allowed", "")
        selected = row.get("selected", "")

        if salient:
            lines.append(f"  salient: {salient}")
        if frontier:
            lines.append(f"  frontier: {frontier}")
        if goal_like:
            lines.append(f"  goal_like: {goal_like}")
        if observations:
            lines.append("  observations:")
            for part in observations.split(";"):
                part = part.strip()
                if part:
                    lines.append(f"    {part}")
        if allowed:
            lines.append(f"  allowed choices: {allowed}")
        if selected:
            lines.append(f"  selected: {selected}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def parse_current_state(text: str) -> dict[str, str]:
    state = {
        "target": "",
        "subgoal": "",
        "status": "idle",
    }
    planner_subgoal = ""
    selected_pattern = re.compile(r"selected target object=([^\s]+)", re.I)
    requested_pattern = re.compile(r"using requested target object=([^\s]+)", re.I)
    planner_pattern = re.compile(r"planner selected:\s*place=([^,]+),\s*angle=([^,]+),\s*objects=(.*)$", re.I)
    final_pattern = re.compile(r"final_goal:([^,\s]+)", re.I)
    subgoal_pattern = re.compile(r"sub_goal:([^,\s]+)", re.I)
    target_pattern = re.compile(r"^target:([^,\s]+)", re.I)

    for raw in text.splitlines():
        line = raw.strip()
        low = line.lower()
        selected = selected_pattern.search(line) or requested_pattern.search(line)
        if selected:
            state["target"] = selected.group(1).strip()
        final_match = final_pattern.search(line)
        if final_match:
            state["target"] = final_match.group(1).strip()
        subgoal_match = subgoal_pattern.search(line)
        if subgoal_match:
            planner_subgoal = subgoal_match.group(1).strip()
        target_match = target_pattern.search(line)
        if target_match:
            planner_subgoal = target_match.group(1).strip()
        planner_match = planner_pattern.search(line)
        if planner_match:
            planner_subgoal = _format_object_list(planner_match.group(3).strip())
        if "episode success" in low or "final goal visible" in low:
            state["status"] = "success"
        elif "episode failed" in low or "not found in current house" in low or "timed out waiting for detection service" in low:
            state["status"] = "failed"
        elif "[debug]" in low or "[timing]" in low:
            if state["status"] not in {"success", "failed"}:
                state["status"] = "exploring"
    state["subgoal"] = planner_subgoal
    return state


def _format_object_list(raw_value: str) -> str:
    try:
        value = ast.literal_eval(raw_value)
        if isinstance(value, (list, tuple)):
            return ", ".join(str(item) for item in value)
    except Exception:
        pass
    return raw_value


def parse_latest_goal_bbox_path(text: str) -> str:
    latest_path = ""
    pattern = re.compile(r"saved final goal bbox:\s*(.+)$", re.I)
    for raw in text.splitlines():
        match = pattern.search(raw.strip())
        if match:
            latest_path = match.group(1).strip()
    return latest_path


def read_tail(path: Path, max_lines: int = 800) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])


def highlighted_html(text: str) -> str:
    return "".join(line_to_html(line) for line in text.splitlines())
