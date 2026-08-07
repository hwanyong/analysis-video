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
