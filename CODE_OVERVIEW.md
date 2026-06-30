# Code Overview

This document explains the current project structure and runtime flow for the
local EfficientNav-based visual-language navigation system.

## 1. High-Level Goal

The project runs an Object-Goal Navigation agent in AI2-THOR/ProcTHOR. The agent
observes the environment, stores object/place descriptions in a navigation map,
asks a visual-language planner which object/place to move toward next, and
reuses/compresses KV cache to reduce repeated planner computation.

The current setup uses:

- AI2-THOR/ProcTHOR for simulation
- InternVL3-1B as the default planner model
- ROS 2 service communication for GroundingDINO object detection
- CLIP text embeddings for semantic similarity
- Navigation-map memory retrieval
- KV-cache reuse and H2O-style cache pruning
- A PySide6 desktop UI for experiment control

## 2. Main Runtime Flow

The main entry point is `efficientnav.py`.

```text
val_auto()
  ├── load ProcTHOR houses
  ├── create ThorSim for each selected house
  ├── choose target object / goal instance
  ├── initialize Navigation_map
  └── val_one_episode(...)
        ├── observe 4 directions around current pose
        ├── call ROS 2 detection service
        ├── parse detected objects
        ├── add place node to Navigation_map
        ├── build/retrieve navigation-map text and KV cache
        ├── call planner
        ├── parse planner target
        ├── move through shortest path toward sub-goal
        ├── check final-goal visibility
        └── report SR/SPL/path metrics
```

The two expected runtime terminals are:

```bash
# Terminal 1: detection service
source ~/miniconda3/bin/activate
conda activate env_dino
source /opt/ros/humble/setup.bash
source ~/DINO_ws/install/setup.bash
python3 -m efficientnav_detection.detection_node
```

```bash
# Terminal 2: desktop UI
source ~/miniconda3/bin/activate
conda activate test
cd efficientnav_desktop_ui
source /opt/ros/humble/setup.bash
source ~/DINO_ws/install/setup.bash
python3 app.py
```

## 3. Core Files

### `efficientnav.py`

This is the main experiment runner. It handles model loading, ROS 2 detection
requests, observation parsing, planner prompting, episode execution, and metric
reporting.

Important sections:

- Model setup
  - Loads InternVL3-1B from `EFFICIENTNAV_PLANNER_MODEL_PATH`
  - Loads CLIP text model from `EFFICIENTNAV_CLIP_PATH`
  - Configures CUDA/device placement

- Detection
  - `DetectionROSClient`
  - `get_detection_ros_client`
  - `detect_goal_in_current_view`
  - `convert_ros_detection_payload_to_box_info_list`

- Observation
  - `get_observation`
  - `parse_observation_response`
  - `normalize_observation_objects`
  - `get_objects_boxes`
  - `get_objects`

- Planning
  - `planning`
  - `parse_planner_response`
  - `parse_planner_response_strict`
  - `parse_planner_response_minimal`
  - `resolve_minimal_llm_choice`

- Episode loop
  - `val_auto`
  - `val_one_episode`

### `navigation_map.py`

This file implements the navigation memory structure.

Main classes:

- `TreeNode`
  - Represents a place node in the explored environment
  - Stores position, direction, children, object descriptions, and optional KV cache

- `Navigation_map`
  - Maintains the tree of explored places
  - Groups similar memories
  - Builds map descriptions for planner prompts
  - Builds and reuses KV cache for repeated map descriptions

Important responsibilities:

- Normalize object labels and descriptions
- Compute semantic similarity between place memories
- Prune low-value structural memories such as walls/floors/ceilings
- Build planner-readable navigation descriptions
- Build KV cache for node/group descriptions
- Apply H2O cache pruning when enabled

### `h2o_cache.py`

This file contains cache compression helpers.

Important concepts:

- Recent tokens
  - The most recent tokens are preserved because they often contain active
    instruction or generation context.

- Heavy tokens
  - Tokens are scored by goal terms, semantic segments, JSON/planner context,
    and optionally attention scores.

- Protected prefix
  - The initial instruction prefix can be preserved to avoid corrupting the
    planner prompt structure.

Main functions:

- `h2o_config`
- `h2o_enabled`
- `build_goal_heavy_scores`
- `build_semantic_heavy_scores`
- `build_segment_heavy_scores`
- `build_attention_heavy_scores`
- `merge_heavy_scores`
- `apply_h2o_to_legacy_cache`

### `thor_adapter.py`

This file adapts AI2-THOR/ProcTHOR into the interface expected by the navigation
code.

Main pieces:

- `load_procthor_houses`
- `ThorSim`
- `ThorAgent`
- `ThorPathfinder`
- `ThorShortestPath`
- `ThorObject`
- `canonical_goal_name`
- yaw/vector conversion helpers

It provides:

- House loading
- Reachable-position cache
- Agent teleport/movement
- RGB/depth/semantic observations
- Approximate shortest path search over reachable points

### `units.py`

This file contains helper functions originally used for GroundingDINO-style
detection utilities.

In the current runtime, object detection normally goes through the ROS 2 service.
The local detection fallback remains available but is not the default path.

### `dino_service_patch/`

This folder stores the ROS 2 detection service source/patch used by the project.
The actual installed runtime package is expected to live in `~/DINO_ws`.

Important files:

- `efficientnav_interfaces/srv/DetectObjects.srv`
- `efficientnav_detection/detection_node.py`

### `efficientnav_desktop_ui/`

This is a local PySide6 desktop UI for running and inspecting experiments.

Main pieces:

- `app.py`
  - Main Qt window
  - Experiment controls
  - Live logs
  - H2O experiment plan builder
  - Results table

- `backend/config.py`
  - Experiment config dataclasses
  - Environment-variable mapping

- `backend/runner.py`
  - Starts/stops `efficientnav.py` as a subprocess

- `backend/log_parser.py`
  - Extracts live state, planner messages, detection logs, H2O logs, and bbox paths

- `backend/result_loader.py`
  - Converts logs into result JSON summaries

- `backend/house_browser.py`
  - Loads/summarizes ProcTHOR houses and object candidates

## 4. Memory and Planning Flow

Each episode repeatedly performs:

1. Observe around the current place
   - Rotate through candidate angles
   - Capture RGB/depth/semantic observations
   - Send RGB images to the detection service

2. Convert detections into memory
   - Normalize object labels
   - Filter low-value or noisy labels
   - Match RGB detections with semantic objects when possible
   - Store object descriptions in a `TreeNode`

3. Build map context
   - Convert the navigation tree into planner text
   - Retrieve relevant place descriptions
   - Optionally build or reuse KV cache

4. Ask planner
   - Prompt the planner to choose a target place/angle/object
   - Parse JSON-like planner output
   - Sanitize invalid or out-of-range choices

5. Move
   - Use the pathfinder to move toward the selected sub-goal
   - Stop early if the final goal becomes visible
   - Update trajectory and metrics

## 5. KV Cache and H2O

The project uses two related ideas:

- KV cache reuse
  - Reuses cached key/value tensors for repeated navigation-map prompt prefixes.
  - Reduces recomputation when planning over similar map descriptions.

- H2O cache pruning
  - Keeps a bounded subset of cached tokens.
  - Preserves recent tokens, instruction tokens, goal-related tokens, retrieved
    memory tokens, and JSON/planner context tokens.

Important environment variables:

```bash
EFFICIENTNAV_USE_KV_CACHE=1
EFFICIENTNAV_USE_H2O=1
EFFICIENTNAV_H2O_CACHE_BUDGET=1024
EFFICIENTNAV_H2O_RECENT_SIZE=256
EFFICIENTNAV_H2O_HEAVY_SIZE=256
EFFICIENTNAV_H2O_PROTECTED_PREFIX=64
EFFICIENTNAV_H2O_PREFIX_OUTSIDE_BUDGET=1
```

## 6. Important Environment Variables

```bash
EFFICIENTNAV_PLANNER_MODEL_PATH=./models/InternVL3-1B
EFFICIENTNAV_CLIP_PATH=~/models/clip-vit-base-patch32
EFFICIENTNAV_USE_ROS2_DETECTION=1
EFFICIENTNAV_ROS2_DETECTION_TIMEOUT=30.0
EFFICIENTNAV_TARGET_OBJECT=tv
EFFICIENTNAV_HOUSE_INDEX=0
EFFICIENTNAV_NUM_HOUSES=1
EFFICIENTNAV_USE_KV_CACHE=1
EFFICIENTNAV_USE_H2O=1
```

## 7. Generated Files

These folders are runtime outputs and are intentionally not committed:

```text
models/
output/
tmp/
images_output/
navigation_images/
efficientnav_desktop_ui/data/
__pycache__/
```

## 8. Current Cleanup State

The project was cleaned so that the repository contains source code and
configuration only. The following were removed or ignored:

- local model checkpoints
- generated navigation images
- temporary outputs
- Python bytecode caches
- old shell run scripts
- duplicate `EfficientNav/` checkout
- local `GroundingDINO/` clone
- old Qwen-specific path/config names

## 9. Notes for Future Work

Possible future cleanup/improvements:

- Remove the non-ROS local GroundingDINO fallback if ROS 2 detection is always used.
- Add command-line arguments for `efficientnav.py` instead of relying mostly on environment variables.
- Split `efficientnav.py` into smaller modules: model setup, detection, planning, episode runner, metrics.
- Add small reproducible test fixtures for parser functions and cache pruning helpers.
- Make model paths configurable through a project-level config file.
