# EfficientNav Desktop UI

브라우저가 아니라 로컬 데스크톱 창으로 뜨는 EfficientNav 실험 관리 UI입니다.
PySide6 기반이며, 기존 EfficientNav 코드는 수정하지 않고 subprocess로 실행합니다.

## 설치

```bash
cd efficientnav_desktop_ui
pip install -r requirements.txt
```

## 실행

Linux/macOS:

```bash
source ~/miniconda3/bin/activate
conda activate test

source /opt/ros/humble/setup.bash
source ~/DINO_ws/install/setup.bash
python app.py
```

Windows:

```bat
run_desktop_ui.bat
```

## 사용 순서

1. `Paths` 탭에서 EfficientNav 프로젝트 루트와 entry script를 지정합니다.
   - 예: project root = repository root
   - entry script = `efficientnav.py`
2. `Experiment` 탭에서 목표 객체, episode, H2O, threshold를 설정합니다.
3. `Run`을 누르면 설정값이 환경변수로 주입되고 기존 스크립트가 실행됩니다.
4. `Live Logs` 탭에서 로그를 확인합니다.
5. `Results` 탭에서 SR, SPL, final_length, 실패 원인 요약을 확인합니다.

## 포함 기능

- 목표 객체 선택: tv, watch, plant, apple 등
- H2O 설정: on/off, budget, recent, heavy, protected_prefix
- detection threshold: small/default/large goal 기준
- episode 설정: house index, start index, goal instance index, seed
- 실행 버튼: full/planner/detection/batch mode
- 로그 viewer: planner, detection, H2O, success/failure 하이라이트
- 결과 요약: SR, SPL, final_length, fail reason
- config 자동 저장

## 주의

`planner`, `detection`, `batch` mode는 기존 `main.py`가 각각 `--planner-only`, `--detection-only`, `--batch` 인자를 지원해야 완전히 동작합니다. 해당 인자가 없으면 `full` mode부터 사용하십시오.

H2O 환경변수 이름은 UI 기준으로 다음을 사용합니다.

- `EFFICIENTNAV_H2O_ENABLED`
- `EFFICIENTNAV_H2O_BUDGET`
- `EFFICIENTNAV_H2O_RECENT_SIZE`
- `EFFICIENTNAV_H2O_HEAVY_SIZE`
- `EFFICIENTNAV_H2O_PROTECTED_PREFIX`

기존 `h2o_cache.py`에서 다른 이름을 사용 중이면 해당 파일 또는 `backend/runner.py`의 매핑을 맞추면 됩니다.
