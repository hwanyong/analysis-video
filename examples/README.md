# examples — 데모 자산을 만드는 스크립트

`docs/media/` 에 들어 있는 공개용 자산은 전부 여기서 만든다. **손으로 만든 그림은
하나도 없다** — 저장소의 어떤 자산이 무엇을 근거로 그렇게 생겼는지 되짚을 수 있어야
하고, 파이프라인이 바뀌면 같은 명령으로 다시 만들 수 있어야 하기 때문이다.

## 왜 합성 영상인가

`testdata/` 의 영상은 전부 타인의 유튜브 강의다. 공개 저장소나 PyPI 페이지에 한
프레임도 실을 수 없다. 그래서 이 도구의 파이프라인을 설명하는 슬라이드를 직접 그려
영상으로 만든다 — 저작권이 깨끗하고, 누구나 다시 만들 수 있다.

## 만드는 순서

세 스크립트는 앞의 산출물을 입력으로 받는다. 이 순서대로 돌린다.

```bash
uv run python examples/make_demo_video.py            # docs/media/demo-pipeline.mp4 + .en.srt
uv run analysis-video analyze docs/media/demo-pipeline.mp4
uv run python examples/make_context_figure.py        # docs/media/context-example.png
uv run python examples/make_gui_screenshot.py        # docs/media/gui-timeline.png
```

| 파일 | 만드는 것 | 입력 |
|---|---|---|
| `make_demo_video.py` | 41초 합성 강의 영상(무음 오디오 트랙 포함)과 짝이 되는 자막 | 없음 |
| `make_context_figure.py` | context.md 한 항목과 그것이 가리키는 프레임을 나란히 놓은 그림 | 위 영상의 분석 결과 |
| `make_gui_screenshot.py` | 실제 분석 결과를 띄운 GUI 창 스크린샷 (오프스크린 캡처) | 위 영상의 분석 결과 |
| `demo_style.py` | 위 두 그림 스크립트가 함께 쓰는 팔레트·글꼴 | — |

새 의존은 하나도 쓰지 않는다. 그리기는 Pillow, 인코딩은 PyAV, 스크린샷은 PySide6 —
전부 이미 워크스페이스의 의존이다.

## 기대 결과

데모 영상은 검출기가 무엇을 하는지 눈에 보이도록 설계했다. 분석이 끝나면 이렇게 나온다.

```
[frames] 사건 4건 — 신호별 anchor 4 cut 4 rate 4
[frames] 화면 4개 중 3개는 시작부터 끝까지 그대로였다 — 끝 상태 후보 생략
[frames] 완료: 채택 6건 / 탈락 0건
          "n_screens": 5, "n_frames": 6, "n_rejected": 0
```

**화면 5개에 이미지 6장**인 것이 핵심이다. 슬라이드 네 장은 뜬 뒤 그대로라 한 장씩만
남고, 판서 화면(10~29초)만 첫 등장과 완성 상태 두 장이 남는다. 숫자가 이와 다르게
나오면 데모가 보여 주려던 성질이 깨진 것이다 — 이유는 `make_demo_video.py` 의
docstring 에 임계별 실측값과 함께 적혀 있다.

## 산출물은 저장소에 들어간다

`docs/media/` 의 mp4·srt·png 는 커밋 대상이다(합계 약 900KB). 분석 결과
`docs/media/demo-pipeline.mp4.analysis/` 는 `.gitignore` 의 `*.analysis/` 규칙으로
이미 제외된다 — 되만들 수 있는 것이라 저장소에 둘 이유가 없다.
