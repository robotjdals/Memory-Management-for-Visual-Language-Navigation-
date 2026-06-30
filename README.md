# Memory Management for Visual-Language Navigation

## Overview

This project is a local experimental implementation based on EfficientNav for
Object-Goal Navigation. The system runs a visual-language navigation agent in
AI2-THOR/ProcTHOR environments using place-based navigation memory, KV-cache
reuse, and H2O-style cache compression.

At each place, the agent observes the environment from multiple directions,
extracts object-level observations, verifies candidate objects through a ROS 2
object detection service and simulator semantic information, and stores the
result as place-based navigation memory. During planning, goal-relevant memory
is retrieved and reused through KV cache to reduce repeated context encoding.
H2O-style cache compression is applied to control KV-cache growth during longer
navigation episodes.

For detailed implementation notes, see [CODE_OVERVIEW.md](CODE_OVERVIEW.md).

## Motivation

Long-horizon visual-language navigation requires the agent to remember observed
places, objects, and movement history. As navigation proceeds, the accumulated
context becomes longer, which increases planning latency and makes small VLM
planners more likely to choose noisy or hallucinated sub-goals.

This project aims to reduce that context burden by:

- storing observations as place-based memory
- retrieving only goal-relevant memory during planning
- reusing KV cache for repeated memory context
- compressing KV cache with H2O-style token selection
- constraining planner output to verified object candidates

## Key Features

- **AI2-THOR / ProcTHOR support**
  - Runs Object-Goal Navigation experiments in ProcTHOR houses through AI2-THOR.

- **Place-based navigation memory**
  - Stores observations by place node, including position, direction-wise
    observations, object candidates, and semantic information.

- **Goal-relevant memory retrieval**
  - Retrieves relevant place memories instead of sending the full navigation
    history to the planner.

- **KV-cache reuse**
  - Converts retrieved memory descriptions into reusable KV cache to reduce
    repeated encoding of the same context.

- **H2O-style KV-cache compression**
  - Preserves recent tokens, goal-related tokens, frontier-related tokens, and
    important prompt segments while pruning lower-value cache tokens.

- **ROS 2-based object detection**
  - Runs GroundingDINO through a separate ROS 2 detection service.

- **Planner constraints**
  - Restricts planner choices to verified place/object candidates to reduce
    hallucinated sub-goal selection.

- **Desktop experiment UI**
  - Provides a PySide6 UI for running experiments, reading live logs, and
    inspecting results.

## Differences from Original EfficientNav

| Component | Original EfficientNav | This Project |
|---|---|---|
| Simulation environment | Habitat-Sim / HM3D | AI2-THOR / ProcTHOR |
| Planner model | LLaVA-v1.6-34B | InternVL3-1B by default |
| Object detection | GroundingDINO in the planner process | ROS 2 detection service |
| Memory | Navigation map caching/retrieval | Place-based memory with structured retrieval |
| KV cache | Discrete KV-cache reuse | KV-cache reuse with DynamicCache conversion/fallback |
| Cache compression | Not included | H2O-style KV-cache compression |
| Planner output | JSON parsing | Allowed-place/object constrained parsing |
| Success check | Goal/distance based | Semantic visibility + RGB detector verification |
| Target setup | Paper reproduction | Local small-VLM experiment setup |

## System Pipeline

```text
AI2-THOR / ProcTHOR Environment
        ↓
Four-direction Observation
        ↓
VLM Object Description
        ↓
ROS 2 / GroundingDINO Object Detection
        ↓
Semantic Instance Verification
        ↓
Place-based Navigation Memory
        ↓
Goal-relevant Memory Retrieval
        ↓
KV Cache Reuse + H2O-style Compression
        ↓
VLM Planner
        ↓
Sub-goal Selection
        ↓
Navigation Execution
        ↓
SR / SPL / Trajectory Length Evaluation
```

## Method Summary

### Observation

At each place, the agent observes four directions: 0, 90, 180, and 270 degrees.
RGB, depth, and semantic observations are collected from AI2-THOR.

The planner-side VLM summarizes visible objects in a JSON-like format:

```json
{
  "Angle": 90,
  "Objects": ["sofa", "table", "doorway"]
}
```

### Object Verification

Detected object names are used as grounding prompts. The ROS 2 detection service
returns bounding boxes, and the system matches these detections with simulator
semantic instances when possible. This reduces noisy language-only object
candidates.

### Place-based Memory

Each observation is stored as a place node containing:

- place index
- agent position
- direction-wise object observations
- verified object candidates
- semantic similarity information
- optional KV cache for the memory description

### KV Cache and H2O Compression

Retrieved place memory can be encoded once and reused through KV cache during
planning. When enabled, H2O-style compression keeps high-value cache tokens and
evicts lower-value tokens when the cache exceeds its budget.

### Planner Constraint

The planner is asked to select a sub-goal only from verified place/object
candidates. The planner output follows this format:

```json
{
  "Place": 1,
  "Angle": 180,
  "Objects": ["doorway"]
}
```

## Evaluation Metrics

| Metric | Description |
|---|---|
| SR | Success Rate: whether the agent successfully reaches or observes the target object |
| SPL | Success weighted by Path Length: success with path efficiency |
| TL | Trajectory Length: total distance traveled by the agent |
| Planning Time | Time spent in planner calls |
| Episode Time | Total runtime per episode |

## Main Files

| File | Description |
|---|---|
| `efficientnav.py` | Main experiment script for observation, planning, navigation, and evaluation |
| `navigation_map.py` | Place-based memory, retrieval, place grouping, and KV-cache construction |
| `h2o_cache.py` | H2O-style KV-cache scoring and compression |
| `thor_adapter.py` | AI2-THOR / ProcTHOR wrapper and pathfinder utilities |
| `units.py` | Object detection helper functions |
| `dino_service_patch/` | ROS 2 detection service source/patch |
| `efficientnav_desktop_ui/` | PySide6 desktop UI for experiments and result inspection |

## Repository Structure

```text
.
├── efficientnav.py
├── navigation_map.py
├── h2o_cache.py
├── thor_adapter.py
├── units.py
├── dino_service_patch/
├── efficientnav_desktop_ui/
├── data/
├── requirements.txt
├── CODE_OVERVIEW.md
└── README.md
```

The following local runtime files are intentionally ignored:

- `models/`
- `output/`
- `tmp/`
- `images_output/`
- `navigation_images/`
- `efficientnav_desktop_ui/data/`
- `__pycache__/`

## Requirements

Install Python dependencies:

```bash
pip install -r requirements.txt
```

The desktop UI has a separate requirements file:

```bash
pip install -r efficientnav_desktop_ui/requirements.txt
```

External resources expected locally:

- Planner model: `./models/InternVL3-1B`
- CLIP model: `~/models/clip-vit-base-patch32`
- ROS 2 detection workspace: `~/DINO_ws`

Model weights are not committed to this repository.

## Running

### 1. Start the ROS 2 Detection Node

Run this in a separate terminal:

```bash
source ~/miniconda3/bin/activate
conda activate env_dino

source /opt/ros/humble/setup.bash
source ~/DINO_ws/install/setup.bash
python3 -m efficientnav_detection.detection_node
```

### 2. Run the Desktop UI

Run this in another terminal:

```bash
source ~/miniconda3/bin/activate
conda activate test

cd efficientnav_desktop_ui
source /opt/ros/humble/setup.bash
source ~/DINO_ws/install/setup.bash
python3 app.py
```

### 3. Run the Main Script Directly

The main experiment can also be run without the UI:

```bash
python3 efficientnav.py
```

Useful environment variables:

```bash
export EFFICIENTNAV_TARGET_OBJECT=tv
export EFFICIENTNAV_HOUSE_INDEX=0
export EFFICIENTNAV_NUM_HOUSES=1
export EFFICIENTNAV_USE_ROS2_DETECTION=1
export EFFICIENTNAV_USE_KV_CACHE=1
export EFFICIENTNAV_USE_H2O=1
export EFFICIENTNAV_PLANNER_MODEL_PATH=./models/InternVL3-1B
```

H2O/KV-cache variables:

```bash
export EFFICIENTNAV_H2O_CACHE_BUDGET=1024
export EFFICIENTNAV_H2O_RECENT_SIZE=256
export EFFICIENTNAV_H2O_HEAVY_SIZE=256
export EFFICIENTNAV_H2O_PROTECTED_PREFIX=64
```

## Notes

- Runtime images and experiment outputs are regenerated during execution.
- The old `run_all.sh`, `run_planner.sh`, and `run_detection.sh` scripts were
  removed because execution now uses direct Python commands and the ROS 2
  detection node.
- The local `GroundingDINO/` clone and model checkpoints are not included in the
  repository.

## Reference

This project builds on the original EfficientNav project:

```text
EfficientNav: On-Device Object-Goal Navigation with Navigation Map Caching and Retrieval
https://github.com/PKU-SEC-Lab/EfficientNav
```

Original paper:

```bibtex
@article{yang2025efficientnav,
  title={EfficientNav: Towards On-Device Object-Goal Navigation with Navigation Map Caching and Retrieval},
  author={Yang, Zebin and Zheng, Sunjian and Xie, Tong and Xu, Tianshi and Yu, Bo and Wang, Fan and Tang, Jie and Liu, Shaoshan and Li, Meng},
  journal={arXiv preprint arXiv:2510.18546},
  year={2025}
}
```
