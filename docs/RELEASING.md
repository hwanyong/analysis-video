# 릴리스 절차

**PyPI에 올린 버전의 파일과 메타데이터는 수정할 수 없다.** 삭제도 안 되고 yank(숨김)만
된다. 그래서 아래 순서는 "되돌릴 수 없는 것"을 마지막에 두도록 짜여 있다.

배포 대상은 **두 개**이고 **버전은 서로 독립**이다.

| 패키지 | 폴더 | 태그 | 버전의 단일 출처 |
|---|---|---|---|
`analysis-video` (코어 CLI) | `packages/core` | `core-v<버전>` | `packages/core/pyproject.toml` |
`analysis-video-gui` (디버깅 GUI) | `packages/gui` | `gui-v<버전>` | `packages/gui/pyproject.toml` |

저장소는 하나다. 나누지 않는 이유는 GUI가 코어의 산출물 스키마(`metadata.json`·
`state.json`)에 묶여 있어서다 — 스키마 변경과 GUI 대응이 한 커밋에 들어가야 하고,
GUI 테스트가 실제 코어 파이프라인을 돌린다.

**순서 규칙: 코어가 먼저다.** GUI는 `analysis-video>=0.1,<0.2` 를 PyPI에서 가져간다.
코어가 없거나 그 범위를 만족하는 버전이 없으면 GUI 설치가 실패한다. 첫 릴리스와,
GUI가 새 코어를 요구하게 되는 릴리스에서 이 순서를 지킨다. `release.yml` 이 GUI
릴리스 때 **그 범위가 색인에서 실제로 해석되는지**를 확인하고(이름의 존재 확인이
아니다) 안 되면 멈춘다. 둘을 같은 날 올리는 절차는 아래
"[코어 → GUI 연속 릴리스](#코어--gui-연속-릴리스)" 에 있다.

아래 1~6은 **한 패키지에 대한 절차**다. `$PKG` 를 `analysis-video` 또는
`analysis-video-gui` 로, `$DIR` 를 `packages/core` 또는 `packages/gui` 로 읽는다.

## 1. 사전 점검

```bash
uv sync
uv run pytest "$DIR/tests"          # 기준선은 "실패 0" — 개수로 게이트하지 않는다(계속 늘어난다)
```

**경로를 지정하는 이유.** 맨몸 `uv run pytest` 는 루트 `pyproject.toml` 의 `testpaths`
대로 **두 패키지를 다** 돈다. GUI의 `analyzed` 픽스처는 실제 파이프라인을 돌려 자막이
없는 영상을 whisper까지 내리므로 HuggingFace에서 모델 가중치를 받는다(`--model tiny`
를 명시해 약 71MB · 네트워크 필요). 코어만 올리는 점검에 그 비용을 낼 이유가 없다.
**GUI를 올릴 때는** 그 비용을 받아들인다 — 리눅스에서는 Qt·오디오 런타임도 필요하다
(`release.yml` 의 `(gui) Qt·오디오 런타임` 스텝이 까는 것과 같은 목록).
`release.yml` 의 `테스트` 스텝도 같은 이유로 대상 패키지의 `tests` 만 돈다.

**데모 자산이 아직 맞는가 (코어를 올릴 때만).** README는 저장소에 든 데모 영상의
분석 결과를 **숫자로** 적는다(화면 5개 · 이미지 6장 · 탈락 0). 검출 임계나 화면
판정이 바뀌면 그 숫자가 조용히 거짓이 된다 — 그림 두 장도 같은 실행에서 나온다.

```bash
uv run analysis-video analyze docs/media/demo-pipeline.mp4 --out "$(mktemp -d)/demo" \
  | python3 -c 'import json,sys; r=json.load(sys.stdin)["stages"][2]["runs"][0]; \
      print(r["n_screens"], r["n_frames"], r["n_rejected"])'
# 5 6 0 이 나와야 한다
```

어긋나면 README의 숫자를 고치는 것이 아니라 **자산을 다시 만든다**
(`examples/README.md` 의 세 스크립트를 순서대로). 데모 영상은 검출기의 기본 임계에
여유를 두고 설계돼 있어서, 여기서 어긋났다는 것은 임계가 그 여유를 넘게 움직였다는
뜻이다. 그 판단을 릴리스 직전에 처음 하지 않는다.

**설치 스모크 — 워크스페이스 밖에서.** 이 저장소 안에서는 `uv.lock` 이 정확한 조합을
못 박아 주므로 최종 사용자가 겪는 버전 계산 실패가 보이지 않는다. 반드시 밖에서 본다.

```bash
TMP=$(mktemp -d) && cp -R "$DIR" "$TMP/pkg" && cd "$TMP"
test ! -e "$TMP/pyproject.toml"     # 워크스페이스 루트를 딸려 보내지 않았는지

# GUI를 점검할 때만: 코어가 아직 PyPI에 없으면 analysis-video>=0.1,<0.2 를 못 찾아
# 모든 조합이 FAIL 한다. 코어를 먼저 만들어 지역 색인으로 넘긴다(install-smoke.yml 과 같은 방식).
[ "$DIR" = packages/gui ] && \
  (cd "$OLDPWD" && uv build --package analysis-video --out-dir "$TMP/idx") && \
  FIND="--find-links $TMP/idx" || FIND=""

uv pip install --dry-run --python 3.12 --target "$TMP/t" --no-build $FIND ./pkg
```

`--no-build` 가 중요하다: 설치 파일(`.whl`)만으로 해석되지 않으면 소스 컴파일로 넘어가
사용자 환경에서 실패한다. 플랫폼별로도 확인한다.

```bash
# 코어
PLATS="aarch64-apple-darwin x86_64-apple-darwin
       x86_64-manylinux_2_28 aarch64-manylinux_2_28 x86_64-pc-windows-msvc"
# GUI — 리눅스 하한이 코어보다 높다(Qt 설치본이 aarch64는 glibc 2.31 부터)
PLATS="aarch64-apple-darwin x86_64-apple-darwin
       x86_64-manylinux_2_28 aarch64-manylinux_2_31 x86_64-pc-windows-msvc"

# 코어는 축이 둘이다 — 기본 설치와 [stt]. GUI는 앞의 것 하나만 본다.
SPECS=(./pkg './pkg[stt]')          # 코어
SPECS=(./pkg)                       # GUI

for SPEC in "${SPECS[@]}"; do
  for PLAT in $PLATS; do
    for PY in 3.11 3.12 3.13 3.14; do
      uv pip install --dry-run --python "$PY" --python-platform "$PLAT" \
         --target "$TMP/t" --no-build "$SPEC" >/dev/null 2>&1 \
        && echo "ok   $SPEC $PLAT py$PY" || echo "FAIL $SPEC $PLAT py$PY"
    done
  done
done
```

기대 결과: 위 목록은 **두 축 모두 전부 통과**. 목록 밖의 알려진 미지원은 Windows
ARM64(두 패키지 모두, `opencv-python-headless` 설치본 부재 — 무조건 의존이라
`[stt]` 와 무관하다)와 리눅스 aarch64 glibc 2.31 미만(GUI).
`macOS + 3.14` 는 `[stt]` 를 붙여도 백엔드가 붙지 않는다(mlx는 cp313까지,
onnxruntime는 macOS cp314 부재) — **해석은 성공하고** `doctor` 가 그 능력이 없다고
보고하는 것이 기대 동작이다. 그 밖의 조합이 실패하면 릴리스를 멈춘다.

여기서 눈으로 보기 어려운 것이 하나 더 있다: **기본 설치에 STT 백엔드가 딸려 오면
안 된다**(딸려 와도 해석은 성공하므로 위 루프로는 안 보인다). 그쪽은
`install-smoke.yml` 의 `resolve` 잡이 해석 결과에서 `mlx-whisper`·`faster-whisper`
를 찾아 검사한다 — 손으로 볼 때는 `--dry-run` 출력(uv는 **stderr** 에 쓴다)에서
그 두 이름을 확인한다.

**GUI를 저장소 밖에서 점검할 때 주의**: `packages/gui/pyproject.toml` 에는
`[tool.uv.sources]` 가 없어야 한다. 거기 있으면 uv가 워크스페이스를 찾다 실패한다
(`references a workspace ... but is not a workspace member`). 그 선언은 루트
`pyproject.toml` 에 있다.

## 2. 빌드

```bash
rm -rf dist-release
uv build --package "$PKG" --out-dir dist-release
```

세 가지를 지킬 것.

- **`--package` 필수.** 맨몸 `uv build` 는 루트에 `[project]` 가 없어 멤버를 빌드하지
  않는다. `--all-packages` 는 두 패키지를 한꺼번에 만들어 업로드 대상이 섞인다.
- **`--out-dir dist-release`.** `dist/` 를 쓰면 과거 산출물과 나란히 남는다.
  매번 지우고 새로 만든다. 두 패키지를 이어서 올릴 때 특히 위험하다.
- **업로드는 파일을 명시**한다. glob 기본값에 맡기면 남아 있던 산출물이 함께 올라간다.

## 3. 검사

```bash
uvx twine check --strict dist-release/*
```

`--strict` 없이는 문제가 있어도 종료코드 0이라 게이트로 쓸 수 없다.

메타데이터에서 **이 세 줄**을 눈으로 확인한다. 하나라도 없으면 올리지 않는다.

```bash
unzip -p dist-release/*.whl '*/METADATA' | \
  grep -E "^(License-Expression|License-File|Description-Content-Type)"
# License-Expression: MIT
# License-File: LICENSE
# Description-Content-Type: text/markdown
unzip -l dist-release/*.whl | grep licenses/LICENSE    # 본문 동봉 확인
```

GUI는 한 줄 더 본다 — 코어 의존이 제대로 찍혔는지.

```bash
unzip -p dist-release/*.whl '*/METADATA' | grep '^Requires-Dist: analysis-video'
# Requires-Dist: analysis-video<0.2,>=0.1
```

## 4. TestPyPI 리허설 (1회)

되돌릴 수 없는 업로드 전에 같은 파일로 한 번 연습한다.

```bash
uvx twine upload --repository testpypi dist-release/*
```

토큰은 https://test.pypi.org/manage/account/token/ 에서 발급한다
(`~/.pypirc` 또는 `TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-...`).

업로드 후 페이지 렌더링(README·라이선스·링크)을 확인하고, **워크스페이스 밖**에서
설치까지 해 본다. TestPyPI에는 의존성이 없으므로 본 PyPI에서 가져오게 한다.

```bash
uvx --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ \
    analysis-video agent-guide | head -5
```

여기서 보는 것은 두 가지다. `--version` 은 "설치·실행이 되는가"만 보지만
`agent-guide` 는 **패키지에 소스가 다 들어갔는가**까지 본다 — 가이드는 모듈 상수에서
import 시점에 조립되므로, 배포물에서 모듈이 하나 빠지면 여기서 죽는다.

`doctor` 도 함께 본다. **기본 설치에서도 종료코드 0** 이고, `capabilities`
`speech-recognition` 이 `available: false` 로 나오는 것이 정상이다 — STT 백엔드는
`[stt]` extra 라 기본 설치에 없고, 없는 것은 고장이 아니라 능력의 부재다
(`cmd_doctor` 독스트링). 여기서 `ok: false` 나 종료코드 4가 나오면 **필수** 모듈이
빠졌다는 뜻이고, 그것은 배포물이 깨졌다는 신호다.

```bash
uvx --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ \
    analysis-video doctor          # ok: true · speech-recognition available: false
uvx --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ \
    'analysis-video[stt]' doctor   # available: true — 다만 326MB를 내려받는다
```

## 5. 본 업로드

```bash
uvx twine upload dist-release/*
```

## 6. 발행 후 확인

```bash
cd /tmp && uvx analysis-video@latest --version      # 워크스페이스 밖에서
cd /tmp && uvx analysis-video@latest agent-guide | head -5
cd /tmp && uvx analysis-video@latest doctor        # ok: true, 종료코드 0
cd /tmp && uvx 'analysis-video[stt]@latest' doctor # 백엔드까지 (내려받기 326MB)
cd /tmp && uvx analysis-video-gui@latest --help    # GUI를 올렸다면
```

> `@latest` 를 붙이는 이유: `uvx` 는 이름만 주면 **이미 캐시에 있는 버전**을 재사용한다.
> 방금 올린 버전을 확인하려는 자리에서 그것은 정확히 틀린 동작이다.

- https://pypi.org/project/analysis-video/ (또는 `-gui`) 에서 README 렌더링·라이선스·
  링크 확인
- [`CHANGELOG.md`](../CHANGELOG.md) 의 해당 패키지 절 확인
- 태그로 올렸다면 GitHub 릴리스 페이지에 배포물(`.whl`·`.tar.gz`)과 그 버전의
  CHANGELOG 절이 실렸는지 확인 (아래 "자동화")

> ⚠️ **4~6번(수동 업로드)과 아래 자동화는 둘 중 하나만 한다.** 태그를 밀면 `release.yml` 이
> 같은 버전을 다시 올리려 들고, `gh-action-pypi-publish` 는 `skip-existing` 기본값이 false 라
> 400(File already exists)으로 잡이 빨갛게 끝난다. 이미 손으로 올렸다면 태그는 기록용으로만
> 남기고(`git tag core-v0.1.0 && git push origin core-v0.1.0`) publish 잡의 실패를 무시하거나,
> 애초에 아래 자동화 경로 하나만 쓴다.

## 코어 → GUI 연속 릴리스

첫 공개가 이 경우다. 두 패키지를 같은 날 올리며, **코어를 먼저 올리고 GUI를 곧바로
잇는다.** 사이에 확인할 것이 하나 있어서 태그 두 개를 한 번에 밀면 안 된다:
GUI는 코어를 **PyPI 색인에서** 가져가는데, 방금 올린 버전이 색인에 나타나기까지는
시차가 있다.

**밀기 전에 끝나 있어야 하는 것** (첫 공개는 버전을 올리지 않지만 아래는 똑같이 필요하다):

- **저장소가 이미 공개(public)여야 한다.** `packages/core/README.md` 는 PyPI 페이지가
  되는데, PyPI는 상대 경로 이미지를 풀지 못하므로 그림을
  `raw.githubusercontent.com/<소유자>/analysis-video/main/…` 절대 주소로 가리킨다.
  저장소가 비공개면 그 주소가 404 라, **PyPI 페이지에 깨진 이미지가 박힌 채로 굳는다**
  — 올린 버전의 메타데이터는 수정할 수 없다. 순서는 저장소 공개 → 태그다.
- 두 프로젝트의 **pending publisher 등록** — 아래 "자동화 › 첫 공개 전에 한 번".
  등록 전에 태그를 밀면 `publish` 잡이 인증에서 거부된다.
- `CHANGELOG.md` 의 두 패키지 절에서 `## [0.1.0] — 미발행` 의 `미발행` 을 **발행일**로
  고친다. `changelog_section.py` 는 미발행 표기에 경고만 내고 통과시키므로(절이 없는
  것과 날짜가 안 박힌 것은 다른 사고다) 이건 사람이 봐야 한다.
- 저장소 루트 `SKILL.md` 생성 (아래 "버전 올리기" 3번). `ci.yml` 의 `changelog` ·
  `skill-sync` 두 잡이 이 둘을 본다 — 태그를 밀기 전에 초록인지 확인한다.

1. **코어 태그를 민다.** 두 태그는 **같은 커밋**에 단다 — 사이에 `pyproject.toml` 을
   고치면 `release.yml` 의 "태그 · pyproject 버전 · CHANGELOG 절" 검사가 어긋난다.
   ```bash
   git tag core-v0.1.0 && git push origin core-v0.1.0
   ```
2. **코어의 release 워크플로가 끝날 때까지 기다린다.** `publish` 잡이 초록이어야
   한다. 실패했으면 GUI 태그를 밀지 않는다 — 없는 코어를 요구하는 GUI가 색인에
   남는다.
3. **색인 전파를 확인한다.** PyPI 프로젝트 페이지에 버전이 보이는 것과, 버전 계산이
   그것을 잡는 것은 다른 일이다. 확인은 **워크스페이스 밖**에서, 캐시를 무시하고:
   ```bash
   cd /tmp && uv pip install --dry-run --refresh --no-deps --no-build \
     --python 3.12 --target /tmp/coregate 'analysis-video>=0.1,<0.2'
   # + analysis-video==0.1.0  ← 이 줄이 나오면 통과 (uv는 이 목록을 stderr에 쓴다)
   ```
   따옴표 안의 범위는 `packages/gui/pyproject.toml` 의 선언과 **같아야 한다** —
   그것이 GUI가 실제로 요구하는 것이다. 보통 1분 안에 잡힌다.
4. **GUI 태그를 민다.**
   ```bash
   git tag gui-v0.1.0 && git push origin gui-v0.1.0
   ```
   `release.yml` 의 `(gui) 코어가 색인에서 실제로 해석되는가` 스텝이 3번과 같은
   검사를 30초 간격 10회(최대 5분)까지 재시도한다. 그래도 안 되면 잡이 멈추고
   아무것도 업로드되지 않는다 — 순서 규칙은 문서가 아니라 이 게이트가 지킨다.
5. **둘 다 확인한다.** 위 "6. 발행 후 확인" 을 두 패키지에 대해 돌린다. GUI는
   설치 자체가 코어를 색인에서 끌어오므로, `uvx analysis-video-gui --help` 가
   성공하면 두 패키지가 실제로 맞물린 것이다.

코어의 메이저·마이너가 올라 GUI의 `<0.2` 상한을 넘게 되면 GUI의 지정자도 함께
고쳐야 하고, 그때는 **코어를 올린 뒤 GUI 지정자를 고친 커밋에** `gui-v*` 태그를 단다
(3번에서 확인하는 범위도 새 지정자다).

## 버전 올리기

버전은 **패키지별로 따로** 올린다. GUI만 고쳤으면 GUI만 올린다.
(`analysis_video.__version__` 은 설치 메타데이터에서 읽으므로 따로 고칠 것이 없다.)

1. 해당 패키지의 `pyproject.toml` 에서 `version` 수정
2. `CHANGELOG.md` 의 **그 패키지 절** 맨 위에 `## [<버전>] — <날짜>` 를 새로 연다
   (그때까지 쌓인 항목을 `## [Unreleased]` 아래 모아 두었다면 그 제목을 바꾸면 된다).
   `release.yml` 이 태그를 받으면 **그 제목의 절을 찾아** 릴리스 노트로 쓰므로, 절이
   없으면 업로드 **전에** 잡이 멈춘다(`.github/scripts/changelog_section.py`).
3. 코어를 올렸다면 **저장소 루트의 `SKILL.md` 를 다시 만든다** — 그 파일에 생성 시점의
   버전이 박히고, `ci.yml` 의 `루트 SKILL.md 가 생성 결과와 같은가` 잡이 대조한다.
   ```bash
   uv run --package analysis-video analysis-video install-skill --dir "$(mktemp -d)"
   # 출력 JSON의 path 가 가리키는 파일을 저장소 루트 SKILL.md 로 덮는다
   ```
4. `uv lock` (워크스페이스 잠금 갱신)
5. 위 1~6 반복
6. 태그는 `core-v<버전>` 또는 `gui-v<버전>`

## 자동화

`.github/workflows/release.yml` 하나가 두 계열 태그(`core-v*`, `gui-v*`)를 모두
받는다. 태그 접두사로 대상을 판별하므로 패키지별 파일 복사가 없다 — 메타데이터
게이트가 한 곳에만 있어 한쪽만 낡는 사고가 안 난다. 수동 실행(`workflow_dispatch`)
에서는 대상을 골라 `dry_run` 으로 검사만 돌릴 수 있다.

태그 하나가 하는 일은 셋이다: **검사 → PyPI 업로드 → GitHub 릴리스 생성.**
마지막 잡(`github-release`)이 배포물(`.whl`·`.tar.gz`)과 그 버전의 CHANGELOG 절을
릴리스 페이지에 올린다. 제목은 `analysis-video 0.1.0` 처럼 **배포물 이름 + 버전**이다 —
태그 계열이 둘이라 `core-v0.1.0` 만으로는 목록에서 어느 패키지인지 읽히지 않는다.
`Latest` 배지는 코어에만 붙인다(이 저장소의 대표는 코어 CLI다).
잡 산출물(`actions/upload-artifact`)은 90일 뒤 만료되고 로그인해야 받을 수 있어
배포물의 영구 사본이 되지 못한다 — 그 자리가 릴리스 페이지다.

### 첫 공개 전에 한 번: PyPI 쪽 등록

PyPI Trusted Publishing(OIDC 기반, 토큰 없는 게시)이라 비밀값이 필요 없다. 다만
**두 프로젝트 각각**에 대해 등록이 필요하고, **아직 발행되지 않은 이름은 등록하는
자리가 다르다.**

- 미발행 프로젝트 → 계정 사이드바의 **pending publisher(발행 대기 게시자)**:
  https://pypi.org/manage/account/publishing/
- 이미 발행된 프로젝트 → 그 프로젝트의 설정 화면
  (`pypi.org/manage/project/<패키지>/settings/publishing/`).
  **이 화면은 프로젝트가 존재해야 생긴다** — 첫 공개 전에는 열 수 없다.

어느 쪽이든 넣는 값은 같다: 저장소 소유자·저장소 이름, 워크플로 파일명
(`release.yml`), 환경명(`pypi`).

두 가지를 알고 있어야 한다.

- **pending publisher 는 이름을 예약하지 않는다.** 등록해 두어도 그 이름이 잠기지
  않고, 다른 사람이 먼저 같은 이름을 올리면 이름은 그쪽 것이 된다. 이름을 확보하는
  유일한 방법은 실제로 올리는 것뿐이다.
- 첫 업로드가 성공하는 순간 pending publisher 는 그 프로젝트의 일반 trusted
  publisher 로 자동 전환된다. 그 뒤로는 프로젝트 설정 화면에서 관리한다.

`release.yml` 의 `publish` 잡은 `pypi` 환경(environment)에서 돈다. 저장소 설정에
같은 이름의 환경이 있어야 하며, 승인자를 걸어 두면 업로드 직전에 사람이 한 번 더
막을 수 있다.
