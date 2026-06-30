# Memory Management for Visual-Language Navigation

This repository contains a local experiment version of EfficientNav for
Object-Goal Navigation. The project focuses on running a visual-language
navigation agent with AI2-THOR/ProcTHOR, ROS 2 object detection, navigation-map
memory retrieval, KV-cache reuse, and H2O-style cache compression.

The code is based on the EfficientNav project, but this repository is organized
around the local experiment setup used in this project rather than the original
paper release layout.

## Main Changes

- Integrated AI2-THOR/ProcTHOR through `thor_adapter.py`
- Uses InternVL3-1B as the default planner model
- Uses a ROS 2 detection service for GroundingDINO object detection
- Added navigation-map memory pruning and retrieval logic
- Added KV-cache and H2O cache management in `h2o_cache.py`
- Added a PySide6 desktop UI for experiment control and result inspection
- Removed generated outputs, cached images, model weights, and local debug files from git

## Repository Structure

```text
.
├── efficientnav.py                 # Main navigation experiment entry point
├── navigation_map.py               # Navigation memory, retrieval, and cache logic
├── h2o_cache.py                    # H2O/KV-cache scoring and compression helpers
├── thor_adapter.py                 # AI2-THOR/ProcTHOR adapter
├── units.py                        # Detection utility wrappers
├── dino_service_patch/             # ROS 2 detection service source/patch
├── efficientnav_desktop_ui/        # PySide6 experiment UI
├── data/                           # Scene dataset config files
├── requirements.txt
└── README.md
```

The following local folders are intentionally ignored:

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

This project expects the following external resources to exist locally:

- Planner model: `/home/min/test/models/InternVL3-1B`
- CLIP model: `/home/min/models/clip-vit-base-patch32`
- ROS 2 detection workspace: `/home/min/DINO_ws`

Model weights are not committed to this repository.

## Object Detection

Object detection is handled by a ROS 2 service. GroundingDINO is installed in
the ROS workspace, not inside this repository.

Start the detection node in a separate terminal:

```bash
source ~/miniconda3/bin/activate
conda activate env_dino

source /opt/ros/humble/setup.bash
source /home/min/DINO_ws/install/setup.bash
python3 -m efficientnav_detection.detection_node
```

The planner connects to this service when `EFFICIENTNAV_USE_ROS2_DETECTION=1`,
which is the default.

## Running

Run the main navigation experiment directly:

```bash
cd /home/min/test
python3 efficientnav.py
```

Useful environment variables:

```bash
export EFFICIENTNAV_TARGET_OBJECT=tv
export EFFICIENTNAV_HOUSE_INDEX=0
export EFFICIENTNAV_NUM_HOUSES=1
export EFFICIENTNAV_USE_KV_CACHE=1
export EFFICIENTNAV_USE_H2O=1
export EFFICIENTNAV_PLANNER_MODEL_PATH=/home/min/test/models/InternVL3-1B
```

## Desktop UI

The desktop UI can launch experiments, show live logs, inspect stored memory,
and summarize result metrics.

```bash
source ~/miniconda3/bin/activate
conda activate test

cd efficientnav_desktop_ui
source /opt/ros/humble/setup.bash
source /home/min/DINO_ws/install/setup.bash
python3 app.py
```

See `efficientnav_desktop_ui/README.md` for details.

## Notes

- `models/` is ignored because planner checkpoints are large.
- Runtime images and experiment outputs are regenerated during execution.
- The old `run_all.sh`, `run_planner.sh`, and `run_detection.sh` scripts were removed because execution now uses direct Python commands and the ROS 2 detection node.

## Citation

This project builds on EfficientNav:

```bibtex
@article{yang2025efficientnav,
  title={EfficientNav: Towards On-Device Object-Goal Navigation with Navigation Map Caching and Retrieval},
  author={Yang, Zebin and Zheng, Sunjian and Xie, Tong and Xu, Tianshi and Yu, Bo and Wang, Fan and Tang, Jie and Liu, Shaoshan and Li, Meng},
  journal={arXiv preprint arXiv:2510.18546},
  year={2025}
}
```
