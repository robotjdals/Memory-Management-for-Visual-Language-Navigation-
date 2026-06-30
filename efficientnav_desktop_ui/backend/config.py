from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RUNS_DIR = DATA_DIR / "runs"
CONFIGS_DIR = DATA_DIR / "configs"
RESULTS_DIR = DATA_DIR / "results"
RESULTS_ARCHIVE_DIR = DATA_DIR / "results_archive"
METRIC_SUMMARY_PATH = DATA_DIR / "metric_summary.json"

for path in (RUNS_DIR, CONFIGS_DIR, RESULTS_DIR, RESULTS_ARCHIVE_DIR):
    path.mkdir(parents=True, exist_ok=True)

SMALL_GOALS = {"apple", "watch", "laptop", "phone", "cellphone", "tablet", "cup", "remote", "book", "bottle", "mug", "box", "statue"}
LARGE_GOALS = {"tv", "television", "bed", "sofa", "chair", "armchair", "toilet", "refrigerator", "fridge", "cabinet", "table", "diningtable", "desk"}
DEFAULT_GOALS = {"plant", "floorlamp", "lamp", "desklamp"}


def goal_size_class(goal: str) -> str:
    normalized = str(goal or "").strip().lower()
    if normalized in SMALL_GOALS:
        return "small"
    if normalized in LARGE_GOALS:
        return "large"
    if normalized in DEFAULT_GOALS:
        return "default"
    return "default"


@dataclass
class H2OConfig:
    enabled: bool = True
    budget: int = 512
    recent: int = 128
    heavy: int = 896
    protected_prefix: int = 64


@dataclass
class ThresholdConfig:
    small_visible_ratio: float = 0.0003
    small_min_bbox_side: int = 12
    small_rgb_min_bbox_side: int = 16
    small_candidate_visible_ratio: float = 0.0001
    small_candidate_min_bbox_side: int = 6
    small_candidate_box_match_ratio: float = 0.005
    small_candidate_detection_min_side: int = 2

    default_visible_ratio: float = 0.002
    default_min_bbox_side: int = 32
    default_rgb_min_bbox_side: int = 40
    default_candidate_visible_ratio: float = 0.0005
    default_candidate_min_bbox_side: int = 16
    default_candidate_box_match_ratio: float = 0.01
    default_candidate_detection_min_side: int = 3

    large_visible_ratio: float = 0.008
    large_min_bbox_side: int = 80
    large_rgb_min_bbox_side: int = 80
    large_candidate_visible_ratio: float = 0.001
    large_candidate_min_bbox_side: int = 24
    large_candidate_box_match_ratio: float = 0.02
    large_candidate_detection_min_side: int = 8


@dataclass
class ExperimentConfig:
    run_id: str = ""
    project_root: str = "/home/min/test"
    entry_script: str = "efficientnav.py"
    target_object: str = "tv"
    custom_target_object: str = ""
    run_mode: str = "full"
    batch_id: str = ""
    batch_order: int = 0
    house_index: int = 0
    start_index: int = 0
    goal_instance_index: int = 0
    seed: int = 7
    num_houses: int = 20
    num_environments: int = 1
    use_ros2_detection: bool = True
    use_kv_cache: bool = True
    planner_model_path: str = "/home/min/test/models/InternVL3-1B"
    clip_path: str = "/home/min/models/clip-vit-base-patch32"
    observation_rotation_pause: float = 0.25
    ros2_detection_timeout: float = 30.0
    h2o: H2OConfig = field(default_factory=H2OConfig)
    threshold: ThresholdConfig = field(default_factory=ThresholdConfig)

    @property
    def effective_target(self) -> str:
        return (self.custom_target_object or self.target_object).strip().lower()

    @property
    def goal_size_class(self) -> str:
        return goal_size_class(self.effective_target)

    def ensure_run_id(self) -> str:
        if not self.run_id:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.run_id = f"{stamp}_{self.effective_target}_house{self.house_index}_seed{self.seed}"
        return self.run_id

    def to_env(self) -> dict[str, str]:
        env = {
            "EFFICIENTNAV_TARGET_OBJECT": self.effective_target,
            "EFFICIENTNAV_NUM_HOUSES": str(self.num_houses),
            "EFFICIENTNAV_NUM_ENVIRONMENTS": str(self.num_environments),
            "EFFICIENTNAV_USE_ROS2_DETECTION": "1" if self.use_ros2_detection else "0",
            "EFFICIENTNAV_USE_KV_CACHE": "1" if self.use_kv_cache else "0",
            "EFFICIENTNAV_PLANNER_MODEL_PATH": self.planner_model_path,
            "EFFICIENTNAV_CLIP_PATH": self.clip_path,
            "EFFICIENTNAV_OBSERVATION_ROTATION_PAUSE": str(self.observation_rotation_pause),
            "EFFICIENTNAV_ROS2_DETECTION_TIMEOUT": str(self.ros2_detection_timeout),
            "EFFICIENTNAV_HOUSE_INDEX": str(self.house_index),
            "EFFICIENTNAV_START_INDEX": str(self.start_index),
            "EFFICIENTNAV_GOAL_INSTANCE_INDEX": str(self.goal_instance_index),
            "EFFICIENTNAV_SEED": str(self.seed),
            "EFFICIENTNAV_EXPERIMENT_SEED": str(self.seed),
            "EFFICIENTNAV_FIXED_START_INDEX": str(self.start_index),
            "EFFICIENTNAV_FIXED_GOAL_INSTANCE_INDEX": str(self.goal_instance_index),
            "EFFICIENTNAV_H2O_ENABLED": "1" if self.h2o.enabled else "0",
            "EFFICIENTNAV_USE_H2O": "1" if self.h2o.enabled else "0",
            "EFFICIENTNAV_H2O_BUDGET": str(self.h2o.budget),
            "EFFICIENTNAV_H2O_CACHE_BUDGET": str(self.h2o.budget),
            "EFFICIENTNAV_H2O_RECENT_SIZE": str(self.h2o.recent),
            "EFFICIENTNAV_H2O_HEAVY_SIZE": str(self.h2o.heavy),
            "EFFICIENTNAV_H2O_PROTECTED_PREFIX": str(self.h2o.protected_prefix),
            "EFFICIENTNAV_H2O_PREFIX_OUTSIDE_BUDGET": "1",
            "EFFICIENTNAV_H2O_USE_ATTENTION_SCORES": "0",
            "EFFICIENTNAV_USE_TRAJECTORY_PROMPT": "1",
        }
        t = self.threshold
        env.update({
            "EFFICIENTNAV_SMALL_GOAL_VISIBLE_RATIO": str(t.small_visible_ratio),
            "EFFICIENTNAV_SMALL_GOAL_MIN_BBOX_SIDE": str(t.small_min_bbox_side),
            "EFFICIENTNAV_SMALL_GOAL_RGB_MIN_BBOX_SIDE": str(t.small_rgb_min_bbox_side),
            "EFFICIENTNAV_SMALL_GOAL_CANDIDATE_VISIBLE_RATIO": str(t.small_candidate_visible_ratio),
            "EFFICIENTNAV_SMALL_GOAL_CANDIDATE_MIN_BBOX_SIDE": str(t.small_candidate_min_bbox_side),
            "EFFICIENTNAV_SMALL_GOAL_CANDIDATE_BOX_MATCH_RATIO": str(t.small_candidate_box_match_ratio),
            "EFFICIENTNAV_SMALL_GOAL_CANDIDATE_DETECTION_MIN_SIDE": str(t.small_candidate_detection_min_side),
            "EFFICIENTNAV_DEFAULT_GOAL_VISIBLE_RATIO": str(t.default_visible_ratio),
            "EFFICIENTNAV_DEFAULT_GOAL_MIN_BBOX_SIDE": str(t.default_min_bbox_side),
            "EFFICIENTNAV_DEFAULT_GOAL_RGB_MIN_BBOX_SIDE": str(t.default_rgb_min_bbox_side),
            "EFFICIENTNAV_DEFAULT_GOAL_CANDIDATE_VISIBLE_RATIO": str(t.default_candidate_visible_ratio),
            "EFFICIENTNAV_DEFAULT_GOAL_CANDIDATE_MIN_BBOX_SIDE": str(t.default_candidate_min_bbox_side),
            "EFFICIENTNAV_DEFAULT_GOAL_CANDIDATE_BOX_MATCH_RATIO": str(t.default_candidate_box_match_ratio),
            "EFFICIENTNAV_DEFAULT_GOAL_CANDIDATE_DETECTION_MIN_SIDE": str(t.default_candidate_detection_min_side),
            "EFFICIENTNAV_LARGE_GOAL_VISIBLE_RATIO": str(t.large_visible_ratio),
            "EFFICIENTNAV_LARGE_GOAL_MIN_BBOX_SIDE": str(t.large_min_bbox_side),
            "EFFICIENTNAV_LARGE_GOAL_RGB_MIN_BBOX_SIDE": str(t.large_rgb_min_bbox_side),
            "EFFICIENTNAV_LARGE_GOAL_CANDIDATE_VISIBLE_RATIO": str(t.large_candidate_visible_ratio),
            "EFFICIENTNAV_LARGE_GOAL_CANDIDATE_MIN_BBOX_SIDE": str(t.large_candidate_min_bbox_side),
            "EFFICIENTNAV_LARGE_GOAL_CANDIDATE_BOX_MATCH_RATIO": str(t.large_candidate_box_match_ratio),
            "EFFICIENTNAV_LARGE_GOAL_CANDIDATE_DETECTION_MIN_SIDE": str(t.large_candidate_detection_min_side),
        })
        return env


def save_config(config: ExperimentConfig) -> Path:
    config.ensure_run_id()
    path = CONFIGS_DIR / f"{config.run_id}.json"
    data = asdict(config)
    data["effective_target"] = config.effective_target
    data["goal_size_class"] = config.goal_size_class
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
