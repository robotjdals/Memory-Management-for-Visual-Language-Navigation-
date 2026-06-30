from __future__ import annotations

import random
import gzip
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def canonical_name(name: str) -> str:
    raw = name or "unknown"
    raw = raw.split("|", 1)[0].split("_", 1)[0]
    normalized = raw.lower().replace(" ", "").replace("-", "")
    aliases = {
        "television": "tv",
        "tvstand": "tv",
        "houseplant": "plant",
        "armchair": "chair",
        "diningchair": "chair",
        "couch": "sofa",
        "refrigerator": "fridge",
    }
    return aliases.get(normalized, normalized)


@dataclass
class HouseSummary:
    index: int
    room_count: int
    object_count: int
    area: float
    size: str
    top_objects: str


@dataclass
class RoomSummary:
    room_id: str
    room_type: str
    object_count: int
    objects: str


def load_houses(seed: int = 7, split: str = "train", limit: int = 50) -> list[dict[str, Any]]:
    try:
        import prior

        dataset = prior.load_dataset("procthor-10k")
        try:
            houses = list(dataset[split])
        except Exception:
            houses = []
            for value in dataset.values():
                houses.extend(list(value))
    except Exception:
        houses = _load_cached_houses(split)
    rng = random.Random(seed)
    rng.shuffle(houses)
    return houses[: max(1, int(limit))]


def _load_cached_houses(split: str) -> list[dict[str, Any]]:
    cache_root = Path.home() / ".prior" / "datasets" / "allenai" / "procthor-10k"
    candidates = sorted(
        cache_root.glob(f"*/{split}.jsonl.gz"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"ProcTHOR cache not found under {cache_root}")
    houses = []
    with gzip.open(candidates[0], "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                houses.append(json.loads(line))
    return houses


def _polygon_area(points: list[dict[str, Any]]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    for idx, point in enumerate(points):
        nxt = points[(idx + 1) % len(points)]
        area += float(point.get("x", 0.0)) * float(nxt.get("z", 0.0))
        area -= float(nxt.get("x", 0.0)) * float(point.get("z", 0.0))
    return abs(area) * 0.5


def _room_id(room: dict[str, Any], fallback: int) -> str:
    return str(room.get("id") or room.get("roomId") or room.get("floorPolygonId") or fallback)


def _room_type(room: dict[str, Any]) -> str:
    return str(room.get("roomType") or room.get("type") or room.get("name") or "room")


def _object_room_id(obj: dict[str, Any]) -> str:
    explicit = str(obj.get("roomId") or obj.get("room") or obj.get("parentRoom") or "")
    if explicit:
        return explicit
    object_id = str(obj.get("id") or "")
    parts = object_id.split("|")
    if len(parts) >= 3 and parts[1] == "surface":
        return f"room|{parts[2]}"
    if len(parts) >= 2 and parts[1].isdigit():
        return f"room|{parts[1]}"
    return ""


def _object_type(obj: dict[str, Any]) -> str:
    return canonical_name(str(obj.get("objectType") or obj.get("id") or obj.get("assetId") or "unknown"))


def _objects_for_house(house: dict[str, Any]) -> list[dict[str, Any]]:
    objects = list(house.get("objects") or [])
    children = []
    for obj in objects:
        children.extend(obj.get("children") or [])
    return objects + children


def _house_area(rooms: list[dict[str, Any]]) -> float:
    total = 0.0
    for room in rooms:
        total += _polygon_area(list(room.get("floorPolygon") or []))
    return total


def _size_label(room_count: int, object_count: int, area: float) -> str:
    score = room_count * 1.5 + object_count / 35.0 + area / 25.0
    if score < 5.0:
        return "small"
    if score < 9.0:
        return "medium"
    return "large"


def summarize_houses(seed: int = 7, split: str = "train", limit: int = 50) -> list[HouseSummary]:
    houses = load_houses(seed=seed, split=split, limit=limit)
    rows = []
    for index, house in enumerate(houses):
        rooms = list(house.get("rooms") or [])
        objects = _objects_for_house(house)
        counts = Counter(_object_type(obj) for obj in objects)
        area = _house_area(rooms)
        top_objects = ", ".join(f"{name}({count})" for name, count in counts.most_common(8))
        rows.append(
            HouseSummary(
                index=index,
                room_count=len(rooms),
                object_count=len(objects),
                area=area,
                size=_size_label(len(rooms), len(objects), area),
                top_objects=top_objects,
            )
        )
    return rows


def object_sets_by_house(seed: int = 7, split: str = "train", limit: int = 200) -> dict[int, set[str]]:
    houses = load_houses(seed=seed, split=split, limit=limit)
    rows = {}
    for index, house in enumerate(houses):
        objects = _objects_for_house(house)
        rows[index] = {_object_type(obj) for obj in objects}
    return rows


def summarize_rooms(house_index: int, seed: int = 7, split: str = "train", limit: int = 50) -> list[RoomSummary]:
    houses = load_houses(seed=seed, split=split, limit=max(limit, house_index + 1))
    if house_index < 0 or house_index >= len(houses):
        return []
    house = houses[house_index]
    rooms = list(house.get("rooms") or [])
    objects = _objects_for_house(house)
    objects_by_room: dict[str, list[str]] = defaultdict(list)
    unmapped = []
    for obj in objects:
        name = _object_type(obj)
        room_id = _object_room_id(obj)
        if room_id:
            objects_by_room[room_id].append(name)
        else:
            unmapped.append(name)

    rows = []
    for fallback, room in enumerate(rooms):
        room_id = _room_id(room, fallback)
        names = objects_by_room.get(room_id, [])
        counts = Counter(names)
        rows.append(
            RoomSummary(
                room_id=room_id,
                room_type=_room_type(room),
                object_count=len(names),
                objects=", ".join(f"{name}({count})" for name, count in counts.most_common(30)),
            )
        )
    if unmapped:
        counts = Counter(unmapped)
        rows.append(
            RoomSummary(
                room_id="-",
                room_type="unmapped/all",
                object_count=len(unmapped),
                objects=", ".join(f"{name}({count})" for name, count in counts.most_common(60)),
            )
        )
    return rows


def object_names_from_room(row: RoomSummary) -> list[str]:
    names = []
    for item in row.objects.split(","):
        name = item.strip().split("(", 1)[0].strip()
        if name:
            names.append(name)
    return names
