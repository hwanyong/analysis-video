# analysis-video

슬라이드 기반 강의 영상을 AI 소비용 컨텍스트로 변환하는 에이전트 친화 CLI.

산출물: 장면 프레임 이미지(원본 해상도) + 대사 타임라인 + 통합 `metadata.json`
(프레임마다 시간·이미지 경로·해당 구간 대사가 묶임).

```bash
uvx analysis-video analyze lecture.mp4      # split + transcribe 후 정지
# → 호출 에이전트가 transcript.json을 읽고 points.json 작성 (텍스트 중요도 분석)
uvx analysis-video frames lecture.mp4 --points points.json
# → metadata.json + frames/
```

에이전트 온보딩: `analysis-video agent-guide >> AGENTS.md`

- 파이프라인 직렬 강제: frames는 transcribe 완료 전 실행 거부(종료코드 3)
- STT 플랫폼별 자동 선택: macOS Apple Silicon(MLX/Metal) → CUDA → CPU(int8)
- 외부 바이너리 의존 0 (PyAV — pip 설치만으로 동작)
- state.json 멱등 재개 — 타임아웃으로 잘려도 같은 명령 재실행이면 이어짐

## 알려진 한계

- **torch 유입(macOS)**: mlx-whisper 0.4.x가 torch를 의존 선언하지만 전사 런타임에서는
  쓰지 않는다. 이 repo의 uv workspace에서는 override로 차단되지만, pip/uvx로 설치하는
  최종 사용자에게는 torch가 함께 설치된다(업스트림 이슈).
- **mlx 요구사항**: mlx 최신 휠은 macOS 14+ / Apple Silicon 전용.
- **Intel Mac**: onnxruntime의 macOS x86_64 휠 중단으로 faster-whisper를 기본 설치하지
  않는다 — STT가 필요하면 `analysis-video[stt-fwhisper]`를 직접 시도(동작 미보장).
- **Windows ARM64**: ctranslate2 휠 부재로 STT 백엔드 없음(`doctor`가 종료코드 4로 안내).
- **CUDA 경로 미실측**: `[cuda]` extra의 pip cudnn/cublas 선로드 배선은 구현됐지만
  로컬에 NVIDIA GPU가 없어 실기 검증 전이다.
