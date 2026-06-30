from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QSpinBox, QSplitter, QTabWidget, QTextEdit,
    QVBoxLayout, QWidget, QTableWidget, QTableWidgetItem
)

from backend.config import (
    ExperimentConfig,
    H2OConfig,
    ThresholdConfig,
    RUNS_DIR,
    RESULTS_DIR,
    RESULTS_ARCHIVE_DIR,
    METRIC_SUMMARY_PATH,
)
from backend.log_parser import (
    read_tail,
    highlighted_html,
    parse_log_text,
    parse_place_memory_text,
    parse_current_state,
    parse_latest_goal_bbox_path,
)
from backend.result_loader import load_recent_results
from backend.runner import start_process, stop_process, finalize_result
from backend.house_browser import canonical_name, object_sets_by_house, summarize_houses, summarize_rooms, object_names_from_room


H2O_EXPERIMENT_BUDGETS = [256]
H2O_EXPERIMENT_EXCLUDED_HOUSES = {1, 17, 21, 31, 34, 36}
COMPARISON_CONDITIONS = [
    ("base", False, None),
    ("base+kv", True, None),
    ("base+kv+h2o/256", True, 256),
]


class EfficientNavDesktopUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EfficientNav Experiment Control Panel")
        self.resize(1320, 860)
        self.process = None
        self.current_log_path: Path | None = None
        self.current_config_path: Path | None = None
        self.current_run_id: str | None = None
        self.current_run_started_at = 0.0
        self.current_timeout_result = False
        self.current_forced_fail_reason: str | None = None
        self.batch_active = False
        self.batch_queue = []
        self.current_batch_row: int | None = None
        self.results_rows: list[dict] = []
        self.summary_result_run_ids: set[str] = self.load_metric_summary_run_ids()

        self.timer = QTimer(self)
        self.timer.setInterval(1200)
        self.timer.timeout.connect(self.refresh_live_views)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        self.config_panel = self.build_config_panel()
        splitter.addWidget(self.config_panel)

        self.tabs = QTabWidget()
        self.live_log = QTextEdit()
        self.live_log.setReadOnly(True)
        self.planner_log = QTextEdit()
        self.planner_log.setReadOnly(True)
        self.detection_log = QTextEdit()
        self.detection_log.setReadOnly(True)
        self.h2o_log = QTextEdit()
        self.h2o_log.setReadOnly(True)
        self.summary_view = QTextEdit()
        self.summary_view.setReadOnly(True)
        self.h2o_experiment_tab = self.build_h2o_experiment_tab()
        self.place_memory_view = QTextEdit()
        self.place_memory_view.setReadOnly(True)
        self.results_table = QTableWidget(0, 18)
        self.results_table.setHorizontalHeaderLabels([
            "Use", "Run ID", "Success", "SR", "SPL", "Final Length", "TL",
            "Episode Time", "Planning Avg", "Planning Total",
            "H2O Evictions", "Avg Seq Before", "Avg Seq After",
            "Condition", "H2O", "Fail Reason", "Goal", "House Size",
        ])
        self.results_table.itemChanged.connect(self.update_results_selection_status)
        self.results_tab = QWidget()
        results_layout = QVBoxLayout(self.results_tab)
        results_buttons = QHBoxLayout()
        apply_selection_btn = QPushButton("Add Checked")
        apply_selection_btn.clicked.connect(self.add_checked_results_to_summary)
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self.select_all_results)
        select_active_btn = QPushButton("Select Active H2O")
        select_active_btn.clicked.connect(self.select_active_h2o_results)
        clear_selection_btn = QPushButton("Clear Checks")
        clear_selection_btn.clicked.connect(self.clear_result_selection)
        clear_summary_btn = QPushButton("Clear Summary")
        clear_summary_btn.clicked.connect(self.clear_metric_summary)
        clear_history_btn = QPushButton("Clear History")
        clear_history_btn.clicked.connect(self.clear_results_history)
        results_buttons.addWidget(apply_selection_btn)
        results_buttons.addWidget(select_all_btn)
        results_buttons.addWidget(select_active_btn)
        results_buttons.addWidget(clear_selection_btn)
        results_buttons.addWidget(clear_summary_btn)
        results_buttons.addWidget(clear_history_btn)
        results_buttons.addStretch()
        self.results_selection_status = QLabel("Summary is empty. Check rows and press Add Checked.")
        results_layout.addLayout(results_buttons)
        results_layout.addWidget(self.results_selection_status)
        results_layout.addWidget(self.results_table)

        self.tabs.addTab(self.live_log, "Live Log")
        self.tabs.addTab(self.place_memory_view, "Stored Memory")
        self.tabs.addTab(self.planner_log, "Planner Debug")
        self.tabs.addTab(self.detection_log, "Detection Debug")
        self.tabs.addTab(self.h2o_log, "H2O Debug")
        self.tabs.addTab(self.h2o_experiment_tab, "H2O Experiment")
        self.tabs.addTab(self.summary_view, "Current Summary")
        self.tabs.addTab(self.results_tab, "Results History")
        splitter.addWidget(self.tabs)
        splitter.setSizes([430, 890])

        self.refresh_results_table()
        QTimer.singleShot(100, self.load_compact_house_browser)

    def build_h2o_experiment_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        setup_box = QGroupBox("Plan")
        form = QFormLayout(setup_box)
        self.exp_targets = QLineEdit("apple,tv,plant")
        self.exp_episodes_per_target = self.spin(1, 10000, 10)
        self.random_episode_count = self.spin(1, 10000, 30)
        self.exp_timeout_minutes = self.spin(1, 10000, 10)
        form.addRow("Targets", self.exp_targets)
        form.addRow("Episodes/Target", self.exp_episodes_per_target)
        form.addRow("Random Run Episodes", self.random_episode_count)
        form.addRow("Conditions", QLabel("base, base+KV, base+KV+H2O budget=256"))
        form.addRow("House Size", QLabel("large only, excluding oversized houses"))
        form.addRow("Timeout Min", self.exp_timeout_minutes)
        layout.addWidget(setup_box)

        buttons = QHBoxLayout()
        build_btn = QPushButton("Build Plan")
        build_btn.clicked.connect(self.build_h2o_plan)
        random_btn = QPushButton("Build Random Run")
        random_btn.clicked.connect(self.build_random_h2o_plan)
        run_btn = QPushButton("Run Plan")
        run_btn.clicked.connect(self.start_h2o_plan)
        skip_btn = QPushButton("Skip Current")
        skip_btn.clicked.connect(self.skip_current_h2o_run)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_h2o_plan)
        clear_results_btn = QPushButton("Clear Results")
        clear_results_btn.clicked.connect(self.clear_results_history)
        buttons.addWidget(build_btn)
        buttons.addWidget(random_btn)
        buttons.addWidget(run_btn)
        buttons.addWidget(skip_btn)
        buttons.addWidget(clear_btn)
        buttons.addWidget(clear_results_btn)
        layout.addLayout(buttons)

        self.exp_status = QLabel("Targets는 쉼표로 입력합니다. oversized house를 제외한 large house 중 target이 있는 house를 자동으로 골라 episode 수를 맞춥니다.")
        self.exp_status.setWordWrap(True)
        layout.addWidget(self.exp_status)

        self.exp_table = QTableWidget(0, 6)
        self.exp_table.setHorizontalHeaderLabels(["#", "Target", "House", "Condition", "Status", "Run ID"])
        self.exp_table.verticalHeader().setVisible(False)
        layout.addWidget(self.exp_table)

        summary_buttons = QHBoxLayout()
        add_checked_summary_btn = QPushButton("Add Checked History")
        add_checked_summary_btn.clicked.connect(self.add_checked_results_to_summary)
        clear_summary_btn = QPushButton("Clear Summary")
        clear_summary_btn.clicked.connect(self.clear_metric_summary)
        summary_buttons.addWidget(add_checked_summary_btn)
        summary_buttons.addWidget(clear_summary_btn)
        summary_buttons.addStretch()
        layout.addLayout(summary_buttons)

        self.metric_summary_status = QLabel("Summary is empty. Check rows in Results History and press Add Checked History.")
        self.metric_summary_status.setWordWrap(True)
        layout.addWidget(self.metric_summary_status)
        self.metric_summary_counts = QLabel("Objects in summary: -")
        self.metric_summary_counts.setWordWrap(True)
        layout.addWidget(self.metric_summary_counts)

        self.exp_summary_table = QTableWidget(0, 9)
        self.exp_summary_table.setHorizontalHeaderLabels([
            "Condition", "Runs", "Success", "Timeouts", "Avg SR", "Avg SPL", "Avg TL",
            "Avg Episode Time", "Avg Planning Time",
        ])
        self.exp_summary_table.verticalHeader().setVisible(False)
        layout.addWidget(self.exp_summary_table)
        return widget

    def build_config_panel(self) -> QWidget:
        panel = QWidget()
        outer = QVBoxLayout(panel)

        self.project_root = QLineEdit("/home/min/test")
        self.entry_script = QLineEdit("efficientnav.py")
        self.target_object = QComboBox()
        self.target_object.addItems(["tv"])
        self.goal_class = QLabel("large")
        self.house_index = self.spin(0, 100000, 0)
        self.seed = self.spin(0, 2_147_483_647, 7)
        self.num_houses = self.spin(1, 100000, 20)
        self.num_envs = self.spin(1, 100000, 1)

        self.custom_target = QLineEdit("")
        self.custom_target.textChanged.connect(self.update_goal_class)

        compact_house_box = QGroupBox("House Browser")
        compact_house_layout = QVBoxLayout(compact_house_box)
        self.compact_house_seed = self.spin(0, 2_147_483_647, 7)
        self.compact_house_limit = self.spin(1, 10000, 50)

        compact_form = QFormLayout()
        self.compact_house_choice = QComboBox()
        self.compact_object_choice = QComboBox()
        self.compact_house_choice.currentIndexChanged.connect(self.load_compact_rooms)
        self.compact_object_choice.currentTextChanged.connect(self.apply_compact_house_selection)
        compact_form.addRow("House", self.compact_house_choice)
        compact_form.addRow("Object", self.compact_object_choice)
        compact_house_layout.addLayout(compact_form)
        self.compact_house_status = QLabel("UI 시작 시 house와 object를 자동으로 불러옵니다.")
        self.compact_house_status.setWordWrap(True)
        compact_house_layout.addWidget(self.compact_house_status)
        self.compact_house_rows = []
        self.compact_room_rows = []
        outer.addWidget(compact_house_box)

        h2o_box = QGroupBox("H2O Cache")
        hform = QFormLayout(h2o_box)
        self.h2o_enabled = QCheckBox("Enabled")
        self.h2o_enabled.setChecked(True)
        self.h2o_budget = self.spin(0, 10_000_000, 512)
        self.h2o_recent = self.spin(0, 10_000_000, 128)
        self.h2o_heavy = self.spin(0, 10_000_000, 896)
        self.h2o_prefix = self.spin(0, 10_000_000, 64)
        hform.addRow("On/Off", self.h2o_enabled)
        outer.addWidget(h2o_box)

        self.threshold_tabs = QTabWidget()
        self.small_fields = self.threshold_page("Small", 0.0003, 12, 16, 0.0001, 6, 0.005, 2)
        self.default_fields = self.threshold_page("Default", 0.002, 32, 40, 0.0005, 16, 0.01, 3)
        self.large_fields = self.threshold_page("Large", 0.008, 80, 80, 0.001, 24, 0.02, 8)

        model_box = QGroupBox("Model & Detection")
        mform = QFormLayout(model_box)
        self.use_ros2 = QCheckBox("Use ROS2 Detection")
        self.use_ros2.setChecked(True)
        self.use_kv = QCheckBox("Use KV Cache")
        self.use_kv.setChecked(True)
        self.planner_model = QLineEdit("/home/min/test/models/InternVL3-1B")
        self.clip_path = QLineEdit("/home/min/models/clip-vit-base-patch32")
        self.rotation_pause = self.dspin(0.0, 120.0, 0.25, 3)
        self.det_timeout = self.dspin(0.1, 3600.0, 30.0, 1)
        mform.addRow("KV Cache", self.use_kv)
        outer.addWidget(model_box)

        exec_box = QGroupBox("Execution")
        egrid = QGridLayout(exec_box)
        run_btn = QPushButton("Run")
        run_btn.clicked.connect(lambda: self.start_run("full"))
        egrid.addWidget(run_btn, 0, 0)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_run)
        egrid.addWidget(self.stop_btn, 0, 1)
        outer.addWidget(exec_box)

        state_box = QGroupBox("Current State")
        state_form = QFormLayout(state_box)
        self.current_target_label = QLabel("-")
        self.current_subgoal_label = QLabel("-")
        self.current_status_label = QLabel("idle")
        state_form.addRow("Target", self.current_target_label)
        state_form.addRow("Subgoal", self.current_subgoal_label)
        state_form.addRow("Status", self.current_status_label)
        outer.addWidget(state_box)

        self.found_object_view = QLabel("찾은 물체 이미지가 아직 없습니다.")
        self.found_object_view.setAlignment(Qt.AlignCenter)
        self.found_object_view.setMinimumSize(320, 240)
        self.found_object_view.setStyleSheet("border: 1px solid #888; background: #111; color: #ddd;")
        outer.addWidget(self.found_object_view)

        outer.addStretch(1)
        return panel

    def threshold_page(self, name, visible, min_side, rgb_side, cand_visible, cand_min, cand_match, cand_det):
        widget = QWidget()
        form = QFormLayout(widget)
        fields = {
            "widget": widget,
            "visible": self.dspin(0.0, 1.0, visible, 6),
            "min_side": self.spin(0, 10000, min_side),
            "rgb_side": self.spin(0, 10000, rgb_side),
            "cand_visible": self.dspin(0.0, 1.0, cand_visible, 6),
            "cand_min": self.spin(0, 10000, cand_min),
            "cand_match": self.dspin(0.0, 1.0, cand_match, 6),
            "cand_det": self.spin(0, 10000, cand_det),
        }
        form.addRow("Semantic Visible Ratio", fields["visible"])
        form.addRow("Semantic Min BBox Side", fields["min_side"])
        form.addRow("RGB Min BBox Side", fields["rgb_side"])
        form.addRow("Candidate Visible Ratio", fields["cand_visible"])
        form.addRow("Candidate Min BBox Side", fields["cand_min"])
        form.addRow("Candidate Box Match Ratio", fields["cand_match"])
        form.addRow("Candidate Detection Min Side", fields["cand_det"])
        return fields

    def spin(self, minv, maxv, value):
        s = QSpinBox()
        s.setRange(minv, maxv)
        s.setValue(value)
        return s

    def dspin(self, minv, maxv, value, decimals):
        s = QDoubleSpinBox()
        s.setRange(minv, maxv)
        s.setDecimals(decimals)
        s.setSingleStep(0.0001 if decimals >= 4 else 0.1)
        s.setValue(value)
        return s

    def browse_project_root(self):
        path = QFileDialog.getExistingDirectory(self, "Select EfficientNav Project Root", self.project_root.text())
        if path:
            self.project_root.setText(path)

    def update_goal_class(self):
        from backend.config import goal_size_class
        goal = self.custom_target.text().strip() or self.target_object.currentText()
        cls = goal_size_class(goal)
        self.goal_class.setText(cls)
        idx = {"small": 0, "default": 1, "large": 2}.get(cls, 1)
        self.threshold_tabs.setCurrentIndex(idx)

    def set_goal_object(self, goal: str):
        normalized_goal = (goal or "").strip().lower()
        if not normalized_goal:
            return
        combo_index = self.target_object.findText(normalized_goal)
        if combo_index >= 0:
            self.target_object.setCurrentIndex(combo_index)
            self.custom_target.setText("")
        else:
            self.custom_target.setText(normalized_goal)
        self.update_goal_class()

    def load_compact_house_browser(self):
        try:
            self.compact_house_rows = summarize_houses(
                seed=self.compact_house_seed.value(),
                split="train",
                limit=self.compact_house_limit.value(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "House load failed", str(exc))
            return
        self.compact_house_choice.blockSignals(True)
        self.compact_house_choice.clear()
        for row in self.compact_house_rows:
            label = (
                f"{row.index} | {row.size} | rooms={row.room_count} "
                f"objects={row.object_count} area={row.area:.1f}"
            )
            self.compact_house_choice.addItem(label, row.index)
        self.compact_house_choice.blockSignals(False)
        self.compact_house_status.setText(f"Loaded {len(self.compact_house_rows)} houses.")
        if self.compact_house_rows:
            self.compact_house_choice.setCurrentIndex(0)
            self.load_compact_rooms()

    def load_compact_rooms(self):
        house_index = self.compact_house_choice.currentData()
        if house_index is None:
            return
        try:
            self.compact_room_rows = summarize_rooms(
                house_index=int(house_index),
                seed=self.compact_house_seed.value(),
                split="train",
                limit=self.compact_house_limit.value(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "Room load failed", str(exc))
            return
        self.house_index.setValue(int(house_index))
        self.seed.setValue(self.compact_house_seed.value())
        self.compact_house_status.setText(f"Selected house={house_index}")
        self.load_compact_objects()

    def load_compact_objects(self):
        names = []
        for row in self.compact_room_rows:
            names.extend(object_names_from_room(row))
        names = sorted(set(names))
        self.compact_object_choice.blockSignals(True)
        self.compact_object_choice.clear()
        self.compact_object_choice.addItems(names)
        self.compact_object_choice.blockSignals(False)
        if names:
            self.compact_object_choice.setCurrentIndex(0)
            self.apply_compact_house_selection(names[0])

    def apply_compact_house_selection(self, goal: str):
        if not goal:
            return
        house_index = self.compact_house_choice.currentData()
        if house_index is not None:
            self.house_index.setValue(int(house_index))
        self.seed.setValue(self.compact_house_seed.value())
        self.set_goal_object(goal)
        self.current_target_label.setText(goal)
        self.compact_house_status.setText(f"Applied house={self.house_index.value()} target={goal}")

    def parse_house_spec(self, spec: str) -> list[int]:
        houses = []
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                start_text, end_text = part.split("-", 1)
                start = int(start_text.strip())
                end = int(end_text.strip())
                step = 1 if end >= start else -1
                houses.extend(range(start, end + step, step))
            else:
                houses.append(int(part))
        return list(dict.fromkeys(houses))

    def build_h2o_plan(self):
        targets = [item.strip().lower() for item in self.exp_targets.text().split(",") if item.strip()]
        if not targets or not COMPARISON_CONDITIONS:
            QMessageBox.warning(self, "Empty plan", "Target과 비교 조건을 하나 이상 선택하세요.")
            return

        self.batch_queue = []
        self.exp_table.setRowCount(0)
        row_index = 0
        skipped_missing = 0
        batch_id = time.strftime("%Y%m%d_%H%M%S")
        episodes_per_target = self.exp_episodes_per_target.value()
        search_limit = max(self.compact_house_limit.value(), episodes_per_target * max(5, len(targets)) * 4, 100)
        house_objects_map = object_sets_by_house(seed=self.seed.value(), split="train", limit=search_limit)
        house_size_map = {
            row.index: row.size
            for row in summarize_houses(seed=self.seed.value(), split="train", limit=search_limit)
        }
        for target in targets:
            houses = self.find_houses_with_target(target, episodes_per_target, house_objects_map, house_size_map)
            if len(houses) < episodes_per_target:
                skipped_missing += (episodes_per_target - len(houses)) * len(COMPARISON_CONDITIONS)
            for house in houses:
                for condition_label, use_kv_cache, h2o_budget in COMPARISON_CONDITIONS:
                    config = self.collect_config("full")
                    config.custom_target_object = target
                    config.target_object = target
                    config.batch_id = batch_id
                    config.batch_order = row_index + 1
                    config.house_index = int(house)
                    config.seed = self.seed.value()
                    config.use_kv_cache = use_kv_cache
                    config.h2o.enabled = h2o_budget is not None
                    if h2o_budget is not None:
                        config.h2o.budget = h2o_budget
                    config.h2o.protected_prefix = 64
                    run_label = condition_label.replace("+", "").replace("/", "")
                    config.run_id = f"{batch_id}_{target}_house{house}_seed{self.seed.value()}_{run_label}_ep{row_index + 1:03d}"
                    self.batch_queue.append((row_index, config))
                    self.exp_table.insertRow(row_index)
                    values = [
                        row_index + 1,
                        target,
                        house,
                        condition_label,
                        "pending",
                        "",
                    ]
                    for col, value in enumerate(values):
                        self.exp_table.setItem(row_index, col, QTableWidgetItem(str(value)))
                    row_index += 1
        self.exp_table.resizeColumnsToContents()
        self.exp_status.setText(
            f"Built {len(self.batch_queue)} runs. "
            f"Missing {skipped_missing} runs because not enough eligible large houses contained the target. "
            f"Excluded houses: {sorted(H2O_EXPERIMENT_EXCLUDED_HOUSES)}."
        )

    def build_random_h2o_plan(self):
        episode_count = self.random_episode_count.value()
        search_limit = max(self.compact_house_limit.value(), episode_count * 4, 100)
        house_objects_map = object_sets_by_house(seed=self.seed.value(), split="train", limit=search_limit)
        candidates = []
        for house_index, object_names in sorted(house_objects_map.items()):
            usable_objects = sorted(
                name for name in object_names
                if name and name not in {"unknown", "wall", "floor", "ceiling", "background"}
            )
            for object_name in usable_objects:
                candidates.append((house_index, object_name))
        if not candidates:
            QMessageBox.warning(self, "Empty plan", "랜덤 episode 후보를 찾지 못했습니다.")
            return

        rng = random.Random(self.seed.value() + int(time.time()))
        rng.shuffle(candidates)
        selected = candidates[:episode_count]
        if len(selected) < episode_count:
            QMessageBox.warning(
                self,
                "Not enough candidates",
                f"요청한 {episode_count}개 중 {len(selected)}개만 만들 수 있습니다.",
            )

        self.batch_queue = []
        self.exp_table.setRowCount(0)
        row_index = 0
        batch_id = time.strftime("%Y%m%d_%H%M%S")
        for house, target in selected:
            condition_label = "random+kv+h2o/512"
            config = self.collect_config("full")
            config.custom_target_object = target
            config.target_object = target
            config.batch_id = batch_id
            config.batch_order = row_index + 1
            config.house_index = int(house)
            config.seed = self.seed.value()
            config.use_kv_cache = True
            config.h2o.enabled = True
            config.h2o.budget = 512
            config.h2o.protected_prefix = 64
            config.run_id = f"{batch_id}_{target}_house{house}_seed{self.seed.value()}_randomkvh2o512_ep{row_index + 1:03d}"
            self.batch_queue.append((row_index, config))
            self.exp_table.insertRow(row_index)
            values = [
                row_index + 1,
                target,
                house,
                condition_label,
                "pending",
                "",
            ]
            for col, value in enumerate(values):
                self.exp_table.setItem(row_index, col, QTableWidgetItem(str(value)))
            row_index += 1

        self.exp_table.resizeColumnsToContents()
        self.exp_status.setText(
            f"Built random plan: {len(selected)} episodes, {len(self.batch_queue)} runs. "
            "KV cache and H2O are enabled for every run. Houses and objects were sampled from all available houses."
        )

    def find_houses_with_target(
        self,
        target: str,
        count: int,
        house_objects_map: dict[int, set[str]],
        house_size_map: dict[int, str] | None = None,
    ) -> list[int]:
        wanted = canonical_name(target)
        houses = [
            house_index
            for house_index, object_names in sorted(house_objects_map.items())
            if wanted in object_names
            and (house_size_map is None or house_size_map.get(house_index) == "large")
            and house_index not in H2O_EXPERIMENT_EXCLUDED_HOUSES
        ]
        return houses[:count]

    def objects_for_house(self, house_index: int) -> set[str]:
        try:
            room_rows = summarize_rooms(
                house_index=int(house_index),
                seed=self.seed.value(),
                split="train",
                limit=max(self.compact_house_limit.value(), int(house_index) + 1),
            )
        except Exception:
            return set()
        names = []
        for row in room_rows:
            names.extend(object_names_from_room(row))
        return {canonical_name(name) for name in names}

    def clear_h2o_plan(self):
        if self.process is not None and self.process.poll() is None:
            QMessageBox.warning(self, "Running", "실행 중에는 plan을 지울 수 없습니다.")
            return
        self.batch_active = False
        self.batch_queue = []
        self.current_batch_row = None
        self.exp_table.setRowCount(0)
        self.exp_status.setText("Plan cleared.")

    def clear_results_history(self):
        if self.process is not None and self.process.poll() is None:
            QMessageBox.warning(self, "Running", "실행 중에는 results를 지울 수 없습니다.")
            return
        result_files = list(RESULTS_DIR.glob("*.json"))
        if not result_files:
            self.summary_result_run_ids.clear()
            self.save_metric_summary_run_ids()
            self.refresh_metric_summary()
            self.exp_status.setText("Results History is already empty.")
            return
        answer = QMessageBox.question(
            self,
            "Clear Results",
            f"Results History {len(result_files)}개를 archive로 옮길까요?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        archive_dir = RESULTS_ARCHIVE_DIR / time.strftime("%Y%m%d_%H%M%S")
        archive_dir.mkdir(parents=True, exist_ok=True)
        moved = 0
        for path in result_files:
            try:
                path.replace(archive_dir / path.name)
                moved += 1
            except OSError:
                continue
        self.summary_result_run_ids.clear()
        self.save_metric_summary_run_ids()
        self.refresh_results_table()
        self.set_metric_summary_status(f"Archived {moved} result files to {archive_dir}.")

    def start_h2o_plan(self):
        if self.process is not None and self.process.poll() is None:
            QMessageBox.warning(self, "Already running", "이미 실행 중인 프로세스가 있습니다. 먼저 Stop을 누르십시오.")
            return
        if not self.batch_queue:
            self.build_h2o_plan()
        if not self.batch_queue:
            return
        self.batch_active = True
        self.exp_status.setText("Batch running.")
        self.start_next_h2o_run()

    def start_next_h2o_run(self):
        if not self.batch_queue:
            self.batch_active = False
            self.current_batch_row = None
            self.exp_status.setText("Batch complete.")
            self.timer.stop()
            self.refresh_results_table()
            return
        row, config = self.batch_queue.pop(0)
        self.current_batch_row = row
        self.exp_table.setItem(row, 4, QTableWidgetItem("running"))
        try:
            self.process, self.current_log_path, self.current_config_path = start_process(config)
            self.current_run_id = config.run_id
            self.current_run_started_at = time.monotonic()
            self.current_timeout_result = False
            self.current_forced_fail_reason = None
        except Exception as exc:
            self.exp_table.setItem(row, 4, QTableWidgetItem(f"start failed: {exc}"))
            self.process = None
            QTimer.singleShot(100, self.start_next_h2o_run)
            return
        self.exp_table.setItem(row, 5, QTableWidgetItem(self.current_run_id or ""))
        self.exp_table.resizeColumnsToContents()
        self.summary_view.setPlainText(f"Run started: {self.current_run_id}\nPID: {self.process.pid}\nLog: {self.current_log_path}")
        self.current_target_label.setText(config.effective_target)
        self.current_subgoal_label.setText("-")
        self.current_status_label.setText("exploring")
        self.timer.start()

    def collect_config(self, mode: str) -> ExperimentConfig:
        t = ThresholdConfig(
            small_visible_ratio=self.small_fields["visible"].value(),
            small_min_bbox_side=self.small_fields["min_side"].value(),
            small_rgb_min_bbox_side=self.small_fields["rgb_side"].value(),
            small_candidate_visible_ratio=self.small_fields["cand_visible"].value(),
            small_candidate_min_bbox_side=self.small_fields["cand_min"].value(),
            small_candidate_box_match_ratio=self.small_fields["cand_match"].value(),
            small_candidate_detection_min_side=self.small_fields["cand_det"].value(),
            default_visible_ratio=self.default_fields["visible"].value(),
            default_min_bbox_side=self.default_fields["min_side"].value(),
            default_rgb_min_bbox_side=self.default_fields["rgb_side"].value(),
            default_candidate_visible_ratio=self.default_fields["cand_visible"].value(),
            default_candidate_min_bbox_side=self.default_fields["cand_min"].value(),
            default_candidate_box_match_ratio=self.default_fields["cand_match"].value(),
            default_candidate_detection_min_side=self.default_fields["cand_det"].value(),
            large_visible_ratio=self.large_fields["visible"].value(),
            large_min_bbox_side=self.large_fields["min_side"].value(),
            large_rgb_min_bbox_side=self.large_fields["rgb_side"].value(),
            large_candidate_visible_ratio=self.large_fields["cand_visible"].value(),
            large_candidate_min_bbox_side=self.large_fields["cand_min"].value(),
            large_candidate_box_match_ratio=self.large_fields["cand_match"].value(),
            large_candidate_detection_min_side=self.large_fields["cand_det"].value(),
        )
        h = H2OConfig(
            enabled=self.h2o_enabled.isChecked(),
            budget=self.h2o_budget.value(),
            recent=self.h2o_recent.value(),
            heavy=self.h2o_heavy.value(),
            protected_prefix=self.h2o_prefix.value(),
        )
        return ExperimentConfig(
            project_root=self.project_root.text().strip(),
            entry_script=self.entry_script.text().strip(),
            target_object=self.target_object.currentText(),
            custom_target_object=self.custom_target.text().strip(),
            run_mode=mode,
            house_index=self.house_index.value(),
            start_index=0,
            goal_instance_index=0,
            seed=self.seed.value(),
            num_houses=self.num_houses.value(),
            num_environments=self.num_envs.value(),
            use_ros2_detection=self.use_ros2.isChecked(),
            use_kv_cache=self.use_kv.isChecked(),
            planner_model_path=self.planner_model.text().strip(),
            clip_path=self.clip_path.text().strip(),
            observation_rotation_pause=self.rotation_pause.value(),
            ros2_detection_timeout=self.det_timeout.value(),
            h2o=h,
            threshold=t,
        )

    def start_run(self, mode: str):
        if self.process is not None and self.process.poll() is None:
            QMessageBox.warning(self, "Already running", "이미 실행 중인 프로세스가 있습니다. 먼저 Stop을 누르십시오.")
            return
        config = self.collect_config(mode)
        try:
            self.process, self.current_log_path, self.current_config_path = start_process(config)
            self.current_run_id = config.run_id
            self.current_run_started_at = time.monotonic()
            self.current_timeout_result = False
            self.current_forced_fail_reason = None
        except Exception as exc:
            QMessageBox.critical(self, "Start failed", str(exc))
            return
        self.summary_view.setPlainText(f"Run started: {self.current_run_id}\nPID: {self.process.pid}\nLog: {self.current_log_path}")
        self.current_target_label.setText(config.effective_target)
        self.current_subgoal_label.setText("-")
        self.current_status_label.setText("exploring")
        self.timer.start()

    def stop_run(self):
        self.batch_active = False
        self.batch_queue = []
        self.current_batch_row = None
        stop_process(self.process)
        self.timer.stop()
        self.finalize_current_result()
        self.refresh_live_views()
        self.refresh_results_table()

    def skip_current_h2o_run(self):
        if not self.batch_active:
            QMessageBox.warning(self, "No batch", "H2O batch 실행 중일 때만 skip할 수 있습니다.")
            return
        if self.process is None or self.process.poll() is not None:
            QMessageBox.warning(self, "No running episode", "현재 실행 중인 episode가 없습니다.")
            return
        self.current_forced_fail_reason = "skipped"
        if self.current_batch_row is not None:
            self.exp_table.setItem(self.current_batch_row, 4, QTableWidgetItem("skipped/pass"))
        stop_process(self.process)
        self.process = None
        self.finalize_current_result()
        self.refresh_results_table()
        self.current_status_label.setText("skipped/pass")
        self.exp_status.setText("Current episode skipped. Moving to next run.")
        QTimer.singleShot(100, self.start_next_h2o_run)

    def finalize_current_result(self):
        if self.current_forced_fail_reason:
            reason = self.current_forced_fail_reason
            self.current_forced_fail_reason = None
            self.save_forced_result(reason)
            return
        if self.current_timeout_result:
            self.save_timeout_result()
            return
        if self.current_run_id and self.current_log_path:
            finalize_result(self.current_run_id, self.current_log_path, self.current_config_path)

    def save_timeout_result(self):
        self.save_forced_result("timeout")

    def save_forced_result(self, reason: str):
        if not self.current_run_id:
            return
        from backend.config import RESULTS_DIR
        from backend.result_loader import load_result_metadata
        import json
        metadata = load_result_metadata(str(self.current_config_path)) if self.current_config_path else {}

        result = {
            "run_id": self.current_run_id,
            "config_path": str(self.current_config_path) if self.current_config_path else None,
            "sr": 0.0,
            "spl": 0.0,
            "final_length": None,
            "tl": None,
            "episode_time": None,
            "planning_time_total": None,
            "planning_time_avg": None,
            "planning_calls": 0,
            "h2o_evictions": 0,
            "h2o_avg_seq_before": None,
            "h2o_avg_seq_after": None,
            "success": False,
            "fail_reason": reason,
            **metadata,
        }
        path = RESULTS_DIR / f"{self.current_run_id}.json"
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    def refresh_live_views(self):
        if self.current_log_path:
            text = read_tail(self.current_log_path, 1200)
        else:
            logs = sorted(RUNS_DIR.glob("*.log"), reverse=True)
            text = read_tail(logs[0], 1200) if logs else "로그가 아직 없습니다."
        self.live_log.setHtml(highlighted_html(text))
        self.live_log.moveCursor(QTextCursor.End)
        self.refresh_place_memory_view(text)
        self.set_filtered_log(self.planner_log, text, ["allowed planner objects", "Place summaries", "planner selected", "raw planner", "sanitized", "Place"])
        self.set_filtered_log(self.detection_log, text, ["detect", "bbox", "semantic", "RGB detector", "final goal visible", "visible_ratio", "box_match"])
        self.set_filtered_log(self.h2o_log, text, ["H2O", "eviction", "heavy", "protected_prefix", "cache", "trim"])
        summary = parse_log_text(text)
        state = parse_current_state(text)
        self.refresh_found_object_image(text)
        if state["target"]:
            self.current_target_label.setText(state["target"])
        if state["subgoal"]:
            self.current_subgoal_label.setText(state["subgoal"])
        status = state["status"]
        if self.process is not None and self.process.poll() is None and status not in {"success", "failed"}:
            status = "exploring"
        self.current_status_label.setText(status)
        if self.batch_active and self.process is not None and self.process.poll() is None:
            elapsed = time.monotonic() - self.current_run_started_at
            timeout_seconds = float(self.exp_timeout_minutes.value()) * 60.0
            if elapsed >= timeout_seconds:
                self.current_timeout_result = True
                if self.current_batch_row is not None:
                    self.exp_table.setItem(self.current_batch_row, 4, QTableWidgetItem("timeout/pass"))
                stop_process(self.process)
                self.process = None
                self.finalize_current_result()
                self.refresh_results_table()
                self.current_status_label.setText("timeout/pass")
                QTimer.singleShot(100, self.start_next_h2o_run)
                return
        self.summary_view.setPlainText(
            "Current Run Summary\n"
            f"Run ID: {self.current_run_id or '-'}\n"
            f"Success: {summary.success}\n"
            f"Final Goal Visible: {summary.final_goal_visible}\n"
            f"Fail Reason: {summary.fail_reason or '-'}\n"
            f"Planner Events: {summary.planner_events}\n"
            f"Detection Events: {summary.detection_events}\n"
            f"H2O Events: {summary.h2o_events}\n"
            f"Log: {self.current_log_path or '-'}\n"
        )
        if self.process is not None and self.process.poll() is not None:
            self.finalize_current_result()
            self.refresh_results_table()
            if self.batch_active:
                if self.current_batch_row is not None:
                    row_status = "success" if summary.success is True else "failed" if summary.success is False else "done"
                    self.exp_table.setItem(self.current_batch_row, 4, QTableWidgetItem(row_status))
                self.process = None
                QTimer.singleShot(100, self.start_next_h2o_run)
            else:
                self.timer.stop()

    def refresh_found_object_image(self, text: str):
        raw_path = parse_latest_goal_bbox_path(text)
        if not raw_path:
            return
        image_path = Path(raw_path)
        if not image_path.is_absolute():
            image_path = Path(self.project_root.text().strip()) / image_path
        if not image_path.exists():
            return
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            return
        scaled = pixmap.scaled(360, 270, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.found_object_view.setPixmap(scaled)

    def refresh_place_memory_view(self, text: str):
        memory_text = parse_place_memory_text(text)
        self.place_memory_view.setPlainText(memory_text)
        self.place_memory_view.moveCursor(QTextCursor.End)

    def set_filtered_log(self, widget: QTextEdit, text: str, keywords: list[str]):
        lines = []
        low_keywords = [k.lower() for k in keywords]
        for line in text.splitlines():
            low = line.lower()
            if any(k in low for k in low_keywords):
                lines.append(line)
        widget.setHtml(highlighted_html("\n".join(lines[-800:]) if lines else "해당 필터 로그가 아직 없습니다."))
        widget.moveCursor(QTextCursor.End)

    def refresh_results_table(self):
        rows = load_recent_results(1000)
        selected_run_ids = self.selected_result_run_ids()
        self.results_rows = rows
        self.results_table.blockSignals(True)
        self.results_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            run_id = str(row.get("run_id", ""))
            use_item = QTableWidgetItem()
            use_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            use_item.setCheckState(Qt.Checked if run_id in selected_run_ids else Qt.Unchecked)
            self.results_table.setItem(r, 0, use_item)
            values = [
                run_id,
                row.get("success", ""),
                row.get("sr", ""),
                row.get("spl", ""),
                row.get("final_length", ""),
                row.get("tl", row.get("final_length", "")),
                row.get("episode_time", ""),
                row.get("planning_time_avg", ""),
                row.get("planning_time_total", ""),
                row.get("h2o_evictions", ""),
                row.get("h2o_avg_seq_before", ""),
                row.get("h2o_avg_seq_after", ""),
                row.get("comparison_condition", row.get("h2o_condition", "")),
                row.get("h2o_condition", ""),
                row.get("fail_reason", ""),
                row.get("target_object", ""),
                row.get("house_size", row.get("house_index", "")),
            ]
            for c, value in enumerate(values):
                self.results_table.setItem(r, c + 1, QTableWidgetItem(str(value)))
        self.results_table.blockSignals(False)
        self.results_table.resizeColumnsToContents()
        self.refresh_metric_summary()

    def selected_result_run_ids(self) -> set[str]:
        selected = set()
        if not hasattr(self, "results_table"):
            return selected
        for row in range(self.results_table.rowCount()):
            item = self.results_table.item(row, 0)
            run_item = self.results_table.item(row, 1)
            if item is not None and run_item is not None and item.checkState() == Qt.Checked:
                selected.add(run_item.text())
        return selected

    def selected_results_rows(self) -> list[dict]:
        selected_run_ids = self.selected_result_run_ids()
        if not selected_run_ids:
            return []
        return [row for row in self.results_rows if str(row.get("run_id", "")) in selected_run_ids]

    def load_metric_summary_run_ids(self) -> set[str]:
        try:
            if not METRIC_SUMMARY_PATH.exists():
                return set()
            data = json.loads(METRIC_SUMMARY_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        if isinstance(data, dict):
            run_ids = data.get("run_ids", [])
        elif isinstance(data, list):
            run_ids = data
        else:
            run_ids = []
        return {str(run_id) for run_id in run_ids if str(run_id)}

    def save_metric_summary_run_ids(self):
        payload = {
            "run_ids": sorted(self.summary_result_run_ids),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            METRIC_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
            METRIC_SUMMARY_PATH.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            self.set_metric_summary_status("Summary save failed. Check data directory permissions.")

    def summary_results_rows(self) -> list[dict]:
        return [
            row for row in self.results_rows
            if str(row.get("run_id", "")) in self.summary_result_run_ids
        ]

    def update_results_selection_status(self, *_):
        selected_run_ids = self.selected_result_run_ids()
        self.set_metric_summary_status(
            f"{len(selected_run_ids)} checked. "
            f"{len(self.summary_result_run_ids)} added to summary."
        )

    def set_metric_summary_status(self, text: str):
        if hasattr(self, "results_selection_status"):
            self.results_selection_status.setText(text)
        if hasattr(self, "metric_summary_status"):
            self.metric_summary_status.setText(text)

    def refresh_metric_summary(self):
        rows = self.summary_results_rows()
        if not rows:
            if hasattr(self, "exp_summary_table"):
                self.exp_summary_table.setRowCount(0)
            if hasattr(self, "metric_summary_counts"):
                self.metric_summary_counts.setText("Objects in summary: -")
            self.set_metric_summary_status(
                "Summary is empty. Check rows in Results History and press Add Checked History."
            )
            return
        self.refresh_comparison_summary(rows)
        self.set_metric_summary_status(
            f"{len(self.selected_result_run_ids())} checked. "
            f"{len(self.summary_result_run_ids)} added to summary."
        )

    def add_checked_results_to_summary(self):
        selected_run_ids = self.selected_result_run_ids()
        if not selected_run_ids:
            self.set_metric_summary_status(
                f"No checked rows. {len(self.summary_result_run_ids)} added to summary."
            )
            return
        self.summary_result_run_ids.update(selected_run_ids)
        self.save_metric_summary_run_ids()
        self.refresh_metric_summary()

    def clear_result_selection(self):
        self.results_table.blockSignals(True)
        for row in range(self.results_table.rowCount()):
            item = self.results_table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.Unchecked)
        self.results_table.blockSignals(False)
        self.update_results_selection_status()

    def select_all_results(self):
        self.results_table.blockSignals(True)
        for row in range(self.results_table.rowCount()):
            item = self.results_table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.Checked)
        self.results_table.blockSignals(False)
        self.update_results_selection_status()

    def clear_metric_summary(self):
        self.summary_result_run_ids.clear()
        self.save_metric_summary_run_ids()
        if hasattr(self, "exp_summary_table"):
            self.exp_summary_table.setRowCount(0)
        self.clear_result_selection()
        self.set_metric_summary_status(
            "Summary cleared. Check rows in Results History and press Add Checked History."
        )

    def select_active_h2o_results(self):
        self.results_table.blockSignals(True)
        for row in range(self.results_table.rowCount()):
            item = self.results_table.item(row, 0)
            run_item = self.results_table.item(row, 1)
            if item is None or run_item is None:
                continue
            run_id = run_item.text()
            result_row = next(
                (result for result in self.results_rows if str(result.get("run_id", "")) == run_id),
                None,
            )
            is_active_h2o = (
                result_row is not None
                and str(result_row.get("h2o_condition", "")).startswith("on/")
                and isinstance(result_row.get("h2o_evictions"), (int, float))
                and result_row.get("h2o_evictions") > 0
            )
            item.setCheckState(Qt.Checked if is_active_h2o else Qt.Unchecked)
        self.results_table.blockSignals(False)
        self.update_results_selection_status()

    def comparison_condition_for_row(self, row: dict) -> str:
        condition = str(row.get("comparison_condition") or "")
        if condition:
            return condition
        config_path = row.get("config_path")
        if config_path:
            try:
                config = json.loads(Path(config_path).read_text(encoding="utf-8"))
                use_kv_cache = bool(config.get("use_kv_cache", True))
                h2o_config = config.get("h2o", {})
                h2o_enabled = bool(h2o_config.get("enabled"))
                if not use_kv_cache:
                    return "base"
                if h2o_enabled:
                    return f"base+kv+h2o/{h2o_config.get('budget')}"
                return "base+kv"
            except Exception:
                pass
        h2o_condition = str(row.get("h2o_condition") or "")
        return "base+kv" if h2o_condition == "off" else f"base+kv+h2o/{h2o_condition.split('/', 1)[-1]}"

    def refresh_comparison_summary(self, rows: list[dict]):
        if not hasattr(self, "exp_summary_table"):
            return
        ordered_keys = [condition[0] for condition in COMPARISON_CONDITIONS]
        groups = {key: [] for key in ordered_keys}
        for row in rows:
            key = self.comparison_condition_for_row(row)
            if key not in groups:
                groups[key] = []
            groups[key].append(row)

        if hasattr(self, "metric_summary_counts"):
            object_counts = {}
            for row in rows:
                goal = str(row.get("target_object") or row.get("goal") or "").strip() or "unknown"
                object_counts[goal] = object_counts.get(goal, 0) + 1
            counts_text = ", ".join(
                f"{goal}={count}" for goal, count in sorted(object_counts.items())
            )
            self.metric_summary_counts.setText(f"Objects in summary: {counts_text or '-'}")

        self.exp_summary_table.setRowCount(len(ordered_keys))
        for r, key in enumerate(ordered_keys):
            group = groups[key]
            values = [
                key,
                len(group),
                sum(1 for item in group if item.get("success") is True),
                sum(1 for item in group if item.get("fail_reason") == "timeout"),
                self.average_metric(group, "sr"),
                self.average_metric(group, "spl"),
                self.average_metric(group, "tl"),
                self.average_metric(group, "episode_time"),
                self.average_metric(group, "planning_time_avg"),
            ]
            for c, value in enumerate(values):
                self.exp_summary_table.setItem(r, c, QTableWidgetItem(str(value)))
        self.exp_summary_table.resizeColumnsToContents()

    def average_metric(self, rows: list[dict], key: str):
        values = [row.get(key) for row in rows if isinstance(row.get(key), (int, float))]
        if not values:
            return ""
        return round(sum(values) / len(values), 4)

    def closeEvent(self, event):
        if self.process is not None and self.process.poll() is None:
            reply = QMessageBox.question(self, "Process running", "실행 중인 프로세스가 있습니다. 종료할까요?")
            if reply == QMessageBox.Yes:
                self.stop_run()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    win = EfficientNavDesktopUI()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
