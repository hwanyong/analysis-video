"""자막(SRT·VTT·SMI)을 전사 출처로 읽고, 써도 되는 자막인지 판정한다.

whisper 전사는 오디오에서 **추론한** 텍스트다. 자막은 사람이 적은 원문이라
고유명사·전문용어·숫자처럼 추론이 흔들리는 자리에서도 흔들리지 않고, 시각도
제작 단계에서 이미 화면에 맞춰져 있다. 그래서 자막이 있으면 자막이 먼저고
whisper는 마지막 폴백이다.

다만 "자막 파일이 있다"와 "그 자막을 써도 된다"는 다르다. 막아야 할 유입 셋:

- **자동 생성 자막(유튜브 ASR)**: 파일명으로는 구분할 수 없다 — yt-dlp는
  `--write-subs`(사람이 적은 것)와 `--write-auto-subs`(기계가 받아쓴 것)를
  **같은 이름**(`영상.ko.vtt`)으로 쓴다. 그러니 내용으로 골라내야 하고, 그
  지문이 롤업이다(뒤 큐가 앞 큐 텍스트로 시작하며 자라나는 형태 — 화면에
  한 줄씩 밀려 올라가는 방송 자막을 흉내 낸 것). 어차피 ASR을 다시 쓸 바에는
  whisper가 낫다(모델을 고를 수 있고 어느 엔진이 돌았는지 기록에 남는다).
- **강제 자막(forced)**: 외국어 대사·간판만 번역한 트랙. 대사 트랙이 아니라
  구멍투성이 주석이라 커버리지가 바닥이다. 이걸 전사로 채택하면 영상의 대부분이
  '(무음)'으로 찍힌다 — 오디오에 말이 있는데도.
- **다른 영상의 자막**: 어간이 같아 딸려 들어온 것. 큐가 영상 길이 밖으로 나간다.

**자막 큐 경계는 화면 검출에 쓰지 않는다.** 자막은 대사 트랙만 채운다.
텍스트만 보고 고른 시각이 시각적 검출과 같은 자리를 놓고 경쟁하면 기준이
흐려지는데, 그건 points.json을 폐기한 이유(cli.py 머리말)와 같은 고장이다.

취급 범위는 SRT·VTT·SMI 셋이다. ASS/SSA는 스타일 정의와 본문이 같은 줄에
섞여 있어 별도 파서가 필요하고, 사이드카로 흔하지도 않아 넣지 않았다.

호출자(cli.run_transcribe)가 쓰는 문은 둘이다 — 쓸 만한 자막을 **한 줄로 세우는**
후보 계층(Candidate·sidecar_candidates·embedded_candidates·rank), 그리고 자막 파일
하나를 읽어 전사 결과로 만드는 result_from_file. 후자는 세 경로가 공유한다:
`--transcript`로 지목한 파일, 영상 옆의 사이드카, split이 컨테이너에서 뽑아 둔
내장 트랙(`subs/track{n}.srt`). **채택 여부만 돌려주고 폴백할지 멈출지는 정하지
않는다** — 그 분기는 사다리를 아는 호출자의 몫이다.

내장 트랙 dict(split.extract_subtitles의 열두 칸)를 **이 모듈이 읽는다**. 반대
방향(split이 Candidate를 만들어 내려보내기)을 택하지 않은 이유는 결합의 값이
다르기 때문이다: 스키마를 읽는 것은 칸 이름 몇 개를 아는 일이지만, 순위 규칙을
split이 갖게 되면 "어느 자막을 쓸 것인가"라는 하나의 정책이 데먹서와 자막
모듈로 쪼개진다. 두 풀을 가로질러 비교해야 하는 규칙은 한 곳에만 있어야 한다.

자막이 아닌 출처(whisper·오디오 없음)의 source 필드는 이 모듈이 만들지 않는다.
전사 결과와 source의 스키마는 stt/base.py(build_result·build_source) 한 곳에
있고, 이 모듈은 자막에서 읽은 값을 채워 그것을 호출할 뿐이다.
"""
import codecs
import html
import re
from dataclasses import dataclass
from pathlib import Path

from . import lang
from .base import build_result, build_source

# ─── 임계 ────────────────────────────────────────────────────────────────
# 자막이라 보기 어려운 하한. 광고 고지·제목 자막만 든 파일이 이 근처다.
MIN_CUES = 5
# Σ(큐 길이)/영상 길이의 하한. 강의·대화 영상의 정상 자막은 대개 0.5를 넘고,
# 강제 자막(외국어 구간만)은 한 자릿수 %에 머문다 — 그 사이를 넉넉히 가른다.
# 낮게 잡은 이유: 침묵이 긴 영상(실습 시연·판서)을 정상인데 거부하면 안 된다.
MIN_COVERAGE = 0.30
# 롤업으로 판정된 인접 쌍의 비율 상한. 자동 생성 자막은 구조상 거의 모든 쌍이
# 롤업이라 1.0에 가깝고(앞 큐를 통째로 물고 자란다), 사람이 적은 자막에서
# 우연히 걸리는 것은 반복 대사·후렴뿐이라 드물다. 사이를 넉넉히 벌려 잡는다.
MAX_ROLLUP = 0.30
# 자막 끝이 영상 길이의 이 배수(+ 아래 여유)를 넘으면 다른 영상의 자막으로 본다.
# 컨테이너 길이와 자막 제작 기준(무편집본)이 조금 어긋나는 것은 흔하므로 배수로,
# 짧은 영상에서 배수만으로는 여유가 0에 수렴하므로 절대 여유도 함께 준다.
SPAN_OVERHANG = 1.10
SPAN_SLACK = 5.0
# SMI 큐 하나의 최대 길이. SMI에는 종료 시각이 없어 다음 SYNC까지로 유도하는데,
# 빈 큐(&nbsp;)를 안 넣은 파일에서는 그 '다음'이 수십 초 뒤일 수 있다. 그러면
# 자막 하나가 엉뚱한 화면까지 늘어나고, align.assign_segments는 "가장 많이 걸친
# 화면"으로 배정하므로 대사가 실제로 말해진 화면이 아니라 뒤 화면에 붙는다.
# 7초는 방송 자막 한 장의 노출 상한 관행이다.
SMI_MAX_CUE = 7.0

# 확장자 → 포맷 이름. 이 이름이 transcript.json의 model 필드로 그대로 나간다.
FORMATS: dict[str, str] = {
    ".srt": "srt",
    ".vtt": "vtt", ".webvtt": "vtt",
    ".smi": "smi", ".sami": "smi",
}
# 후보가 여럿일 때의 포맷 선호도 — 종료 시각의 확실성 순이다. SRT·VTT는 큐마다
# 종료 시각이 적혀 있고, SMI는 유도해야 한다(위 SMI_MAX_CUE 참조).
# SRT를 VTT보다 앞에 두는 이유: 자동 생성 자막은 VTT로만 배포된다.
FORMAT_ORDER = ("srt", "vtt", "smi")


@dataclass(frozen=True)
class Cue:
    """자막 한 장. 정제까지 끝난 상태로만 만든다(text에 마크업이 남지 않는다)."""
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Report:
    """검증 결과. reason이 있으면 거부 사유이고, 지표는 채택·거부 모두에서 채운다
    — 거부한 자막이 왜 거부됐는지 숫자로 남아야 사용자가 판단할 수 있다."""
    ok: bool
    reason: str | None
    n_cues: int
    coverage: float
    span: tuple[float, float] | None
    rollup: float


# ─── 인코딩 ──────────────────────────────────────────────────────────────
# 한국어 SMI는 대개 CP949(EUC-KR 상위집합)로 저장돼 있다 — SAMI가 널리 쓰이던
# 시기의 기본 인코딩이고, 지금도 배포본은 그대로다.
_ENCODINGS = ("utf-8", "cp949")
# latin-1은 어떤 바이트열도 예외 없이 읽는다. 사다리의 끝을 여기로 두는 것은
# "읽히는 파일 앞에서 죽지 않는다"를 택하고 깨진 글자를 감수한 것이다 —
# 어차피 다음 단계의 검증이 내용을 보고 판정한다.
_FALLBACK_ENCODING = "latin-1"


def decode_bytes(data: bytes) -> tuple[str, str]:
    """자막 바이트 → (텍스트, 실제로 쓴 인코딩 이름).

    BOM이 있으면 그것이 정답이므로 먼저 본다. 없으면 UTF-8 → CP949 순인데,
    이 순서가 뒤집히면 안 된다: CP949는 바이트 대부분을 받아들여 UTF-8 문서를
    깨진 글자로 '성공적으로' 읽어 버린다."""
    for bom, enc in ((codecs.BOM_UTF8, "utf-8-sig"),
                     (codecs.BOM_UTF16_LE, "utf-16"),
                     (codecs.BOM_UTF16_BE, "utf-16")):
        if data.startswith(bom):
            try:
                return data.decode(enc), enc
            except UnicodeDecodeError:
                break
    for enc in _ENCODINGS:
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode(_FALLBACK_ENCODING), _FALLBACK_ENCODING


# ─── 마크업 정제 ─────────────────────────────────────────────────────────
# 지울 태그는 화이트리스트로 못박는다. `<[^>]+>` 무차별 제거는 강의 자막에
# 자주 나오는 부등호·제네릭 표기("a <b> c", "List<T>")를 본문째로 먹는다.
# p·body·sami·head·style·sync는 SMI 구조 태그로, 본문 자리에 나올 일이 없다.
_TAGS = re.compile(
    r"</?(?:i|b|u|s|em|strong|font|c|v|lang|ruby|rt|rp"
    r"|p|body|sami|head|title|style|sync)\b[^>]*>", re.IGNORECASE)
# 줄바꿈 태그는 지우지 말고 공백으로 바꾼다 — 지우면 "hello<br>world"가 한 단어가 된다.
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
# VTT 인라인 타이밍 `<00:00:01.000>` — 자동 생성 자막이 단어마다 박아 넣는다.
_INLINE_TS = re.compile(r"<\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3}>")
# ASS 오버라이드 `{\an8}` `{\pos(192,50)}`. 여는 중괄호 **뒤에 역슬래시**가 오는
# 것만 지운다 — 강의 자막에는 코드가 나오므로 `{ ... }`를 무조건 지우면 본문이 없어진다.
_ASS = re.compile(r"\{\\[^}]*\}")
# VTT 화자 태그 `<v 이름>` / `<v.loud 이름>`.
_VOICE = re.compile(r"<v(?:\.[^\s>]+)*\s+([^>]+)>", re.IGNORECASE)


def clean_text(s: str, *, unescape: bool = True) -> str:
    """자막 원문 한 장 → 마크다운 본문에 그대로 넣을 수 있는 한 줄.

    context.py:84가 segment의 text를 그대로 이어 붙여 AI에게 주므로, 태그가
    남으면 그 토큰을 AI가 읽는다. 엔티티 해제를 **태그 제거 뒤에** 하는 것이
    이 함수의 유일한 순서 제약이다: 먼저 풀면 작성자가 글자로 적은 `&lt;i&gt;`가
    진짜 태그로 둔갑해 본문이 지워진다.

    `unescape=False`가 있는 이유: 엔티티 해제는 이 함수에서 **유일하게 멱등이
    아닌** 단계다. 같은 글자에 두 번 걸면 한 겹씩 더 벗겨진다 — 실측
    `&amp;lt;i&amp;gt;` → `&lt;i&gt;` → `<i>`, 그리고 세 번째에는 태그로 인식돼
    본문째 사라진다. split이 내장 트랙을 subs/track{n}.srt로 쓸 때 여기서 풀면,
    transcribe가 그 파일을 사이드카와 **구분 없이** 되읽으면서 두 번째 해제가
    걸린다. 그래서 쓰는 쪽은 끄고 읽는 쪽만 한 번 푼다: 산출된 SRT가 밖에서
    받아 온 자막 파일과 똑같이 취급되고, 정제 규칙이 두 벌로 갈리지 않는다.

    끄면 `&nbsp;`가 공백으로 접히지 않아 "빈 큐" 판정이 그만큼 좁아진다. 그 판정을
    쓰는 것은 SMI(파일 파싱, 항상 켠 채로 온다)뿐이고, 끄는 쪽인 내장 트랙은
    ASS·subrip 페이로드라 빈 큐를 오버라이드/드로잉 제거로 가려낸다."""
    s = _ASS.sub("", s)
    s = _INLINE_TS.sub("", s)
    s = _BR.sub(" ", s)
    s = _TAGS.sub("", s)
    if unescape:
        s = html.unescape(s)
    # &nbsp;가 풀린 U+00A0도 공백류에 함께 넣는다 — SMI의 빈 큐가 여기서 빈
    # 문자열이 되어야 "여기서 앞 자막이 끝난다"는 신호로 쓸 수 있다.
    return re.sub(r"[\s\u00a0]+", " ", s).strip()


# ─── 파서 ────────────────────────────────────────────────────────────────
# HH:MM:SS,mmm(SRT) · HH:MM:SS.mmm / MM:SS.mmm(VTT) 를 한 패턴으로 받는다.
_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
# 큐가 아닌 VTT 블록. 사양상 NOTE 안에는 "-->"가 못 들어가므로 아래 화살표
# 조건만으로도 걸러지지만, 깨진 파일에서 본문이 큐로 둔갑하는 것을 막는다.
_NON_CUE_BLOCKS = ("NOTE", "STYLE", "REGION")


def _seconds(m: re.Match) -> float:
    h, mm, ss, frac = m.groups()
    return int(h or 0) * 3600 + int(mm) * 60 + int(ss) + int(frac) / 10 ** len(frac)


def _parse_timed_blocks(text: str) -> list[Cue]:
    """SRT·VTT 공통 파서 — 두 포맷은 큐 문법이 같다.

    블록(빈 줄로 갈린 덩어리)에서 "-->"가 든 줄을 찾고, 그 줄의 앞 두 타임스탬프가
    시작·끝, 그 아래가 본문이다. 이 한 규칙으로 SRT의 큐 번호, VTT의 WEBVTT
    머리말·큐 식별자, 타임스탬프 줄 뒤의 큐 설정(line:/position:/align:)이 전부
    자동으로 걸러진다 — 포맷별로 갈래를 나누면 늘어나기만 하고 나아지지 않는다."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for block in re.split(r"\n[ \t]*\n+", normalized):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines or lines[0].split(maxsplit=1)[0].upper() in _NON_CUE_BLOCKS:
            continue
        idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if idx is None:
            continue
        stamps = list(_TS.finditer(lines[idx]))
        if len(stamps) < 2:
            continue
        start, end = _seconds(stamps[0]), _seconds(stamps[1])
        body = "\n".join(lines[idx + 1:])
        speaker = _VOICE.search(body)
        text_out = clean_text(body)
        if speaker:
            # 화자는 text 안에 넣는다. segments의 별도 키로 두면 context.md가
            # text만 렌더하므로 AI에게 영영 닿지 않는다(= 죽은 데이터).
            # 화자가 이어져도 매 큐에 붙이는 이유: 화면 경계에서 대사가 갈릴 때
            # (align.assign_segments는 문장을 한 화면에만 배정한다) 이름이 붙은
            # 큐만 다른 화면으로 가면 나머지가 화자 미상이 된다.
            text_out = f"{clean_text(speaker.group(1))}: {text_out}".strip()
        if end > start and text_out:
            cues.append(Cue(start, end, text_out))
    return cues


_SYNC = re.compile(r"<sync\b([^>]*)>", re.IGNORECASE)
_START_ATTR = re.compile(r"\bstart\s*=\s*\"?(-?\d+)", re.IGNORECASE)
_P = re.compile(r"<p\b([^>]*)>", re.IGNORECASE)
_CLASS_ATTR = re.compile(r"\bclass\s*=\s*\"?([\w.-]+)", re.IGNORECASE)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BODY_END = re.compile(r"</body>", re.IGNORECASE)


def _smi_paragraphs(body: str) -> dict[str | None, str]:
    """한 SYNC 안의 <P Class=...> 들 → {클래스: 정제된 텍스트}.

    다국어 SMI(한국어 KRCC + 영어 ENCC)는 SYNC 하나에 P를 여러 개 둔다. 전부
    이으면 한 대사가 "안녕하세요 Hello"가 된다."""
    marks = list(_P.finditer(body))
    if not marks:
        return {None: clean_text(body)}
    out: dict[str | None, str] = {}
    for i, m in enumerate(marks):
        cm = _CLASS_ATTR.search(m.group(1))
        cls = cm.group(1).upper() if cm else None
        stop = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        chunk = clean_text(body[m.end():stop])
        if not out.get(cls):     # 같은 클래스가 두 번 나오면 내용이 있는 쪽을 남긴다
            out[cls] = chunk
    return out


def _parse_smi(text: str) -> tuple[list[Cue], list[str]]:
    """SAMI — **종료 시각이 구조적으로 없다.** 여기가 이 모듈에서 제일 위험한 곳.

    `<SYNC Start=1000>`은 시작만 준다. 종료는 다음 SYNC의 시작이고, 대사와 대사
    사이의 침묵은 제작 도구가 빈 큐(`<P>&nbsp;`)를 넣어 표시한다. 그 빈 큐를
    못 거르면 자막 하나가 다음 대사가 나올 때까지 늘어나 엉뚱한 화면에 배정된다
    — 정제 결과가 빈 문자열인 큐를 버리는 것이 그 방어다.

    빈 큐를 안 넣은 파일도 있으므로 유도한 길이는 SMI_MAX_CUE에서 자른다."""
    notes: list[str] = []
    doc = _COMMENT.sub(" ", text)
    end_tag = _BODY_END.search(doc)
    if end_tag:
        doc = doc[:end_tag.start()]   # </BODY></SAMI> 꼬리가 마지막 큐에 붙는 것을 막는다

    marks = list(_SYNC.finditer(doc))
    entries: list[tuple[float, dict[str | None, str]]] = []
    for i, m in enumerate(marks):
        sm = _START_ATTR.search(m.group(1))
        if sm is None or int(sm.group(1)) < 0:
            continue
        stop = marks[i + 1].start() if i + 1 < len(marks) else len(doc)
        entries.append((int(sm.group(1)) / 1000.0, _smi_paragraphs(doc[m.end():stop])))
    entries.sort(key=lambda e: e[0])
    if not entries:
        return [], notes

    order = list(dict.fromkeys(cls for _, ps in entries for cls in ps))
    pick = order[0]
    if len(order) > 1:
        # 결정적 규칙: 비어 있지 않은 큐가 가장 많은 클래스, 동수면 먼저 나온 쪽.
        counts = {c: sum(1 for _, ps in entries if ps.get(c)) for c in order}
        pick = max(order, key=lambda c: (counts[c], -order.index(c)))
        shown = ", ".join(str(c) for c in order)
        notes.append(f"SMI에 자막 클래스가 {len(order)}종({shown}) 있어 "
                     f"비어 있지 않은 큐가 가장 많은 '{pick}'({counts[pick]}건)을 골랐습니다")

    cues, capped = [], 0
    for i, (start, ps) in enumerate(entries):
        body = ps.get(pick) or ""
        if not body:
            continue          # 빈 큐 = 여기서 앞 자막이 끝난다는 표시
        nxt = entries[i + 1][0] if i + 1 < len(entries) else start + SMI_MAX_CUE
        end = min(nxt, start + SMI_MAX_CUE)
        if nxt > end:
            capped += 1
        if end > start:
            cues.append(Cue(start, end, body))
    if capped:
        notes.append(f"SMI는 종료 시각이 없어 다음 자막까지로 유도했고, 그중 {capped}건은 "
                     f"{SMI_MAX_CUE:.0f}초에서 잘랐습니다(빈 큐가 없는 파일)")
    return cues, notes


def parse(text: str, fmt: str) -> tuple[list[Cue], list[str]]:
    """자막 텍스트 → (큐 목록, 메모). fmt는 FORMATS의 값("srt"|"vtt"|"smi").

    메모는 파싱 중 내린 판단(SMI 클래스 선택 등)이다 — 조용히 고르면 나중에
    "왜 이 대사만 실렸나"를 되짚을 수 없다. 시작 시각 순으로 정렬해 돌려준다:
    커버리지·롤업·구간 판정이 전부 순서를 전제한다."""
    if fmt == "smi":
        cues, notes = _parse_smi(text)
    elif fmt in ("srt", "vtt"):
        cues, notes = _parse_timed_blocks(text), []
    else:
        raise ValueError(f"지원하지 않는 자막 포맷: {fmt}")
    return sorted(cues, key=lambda c: (c.start, c.end)), notes


# ─── 검증 ────────────────────────────────────────────────────────────────
def _covered_seconds(cues: list[Cue], duration: float) -> float:
    """큐가 덮은 시간의 **합집합**. 그냥 더하면 안 된다 — 두 화자가 동시에
    말하는 구간은 큐가 겹쳐서, 총합이 영상 길이를 넘기기까지 한다. 그러면
    강제 자막이 커버리지를 부풀려 방어를 통과할 수 있다."""
    total, lo, hi = 0.0, None, None
    for c in sorted(cues, key=lambda x: x.start):
        a, b = max(c.start, 0.0), min(c.end, duration)
        if b <= a:
            continue
        if hi is None or a > hi:
            if hi is not None:
                total += hi - lo
            lo, hi = a, b
        else:
            hi = max(hi, b)
    return total + (hi - lo if hi is not None else 0.0)


def _rollup_ratio(cues: list[Cue]) -> float:
    """자동 생성 자막의 지문 — 인접한 두 큐에서 뒤 큐가 앞 큐 텍스트로 시작하는 비율.

    유튜브 ASR은 확정된 앞부분을 그대로 물고 새 단어를 붙여 다시 내보낸다
    ("안녕하세요" → "안녕하세요 여러분" → "안녕하세요 여러분 오늘은"). 사람이
    적은 자막에서는 이런 성장이 반복 대사·후렴에서 드물게만 나온다."""
    if len(cues) < 2:
        return 0.0
    hits, prev = 0, " ".join(cues[0].text.split()).casefold()
    for c in cues[1:]:
        cur = " ".join(c.text.split()).casefold()
        if prev and cur.startswith(prev):
            hits += 1
        prev = cur
    return hits / (len(cues) - 1)


def evaluate(cues: list[Cue], duration: float) -> Report:
    """이 자막을 전사로 채택해도 되는가. 거부 사유는 사용자가 읽을 한 문장으로 낸다.

    검사 순서는 사유의 우선순위다 — 자동 생성 자막은 큐도 많고 커버리지도 높아
    다른 검사를 전부 통과하므로, 걸렸을 때 그 사실이 사유가 되어야 한다.
    duration을 모르면(0 이하) 시간 기반 두 검사는 건너뛴다 — 판정할 근거가 없는
    것을 '거부'로 바꾸면 멀쩡한 자막을 잃는다."""
    n = len(cues)
    span = (min(c.start for c in cues), max(c.end for c in cues)) if cues else None
    coverage = _covered_seconds(cues, duration) / duration if duration > 0 else 0.0
    rollup = _rollup_ratio(cues)

    reason = None
    if n < MIN_CUES:
        reason = (f"자막 큐가 {n}개뿐이라 대사 트랙으로 보기 어렵습니다"
                  f"(최소 {MIN_CUES}개)")
    elif rollup > MAX_ROLLUP:
        reason = (f"큐의 {rollup:.0%}가 앞 큐를 물고 자라는 롤업 형태입니다 — "
                  f"자동 생성 자막(ASR)으로 판단해 거부합니다(상한 {MAX_ROLLUP:.0%})")
    elif duration > 0 and span is not None and (
            span[1] > duration * SPAN_OVERHANG + SPAN_SLACK or span[0] < -SPAN_SLACK):
        reason = (f"자막 구간 {span[0]:.0f}~{span[1]:.0f}초가 영상 길이"
                  f"({duration:.0f}초) 밖으로 크게 벗어납니다 — 다른 영상의 자막이거나 "
                  "타임코드가 깨졌습니다")
    elif duration > 0 and coverage < MIN_COVERAGE:
        reason = (f"자막이 영상의 {coverage:.0%}만 덮습니다 — 외국어 구간만 번역한 "
                  f"강제 자막으로 의심됩니다(최소 {MIN_COVERAGE:.0%})")

    return Report(ok=reason is None, reason=reason, n_cues=n,
                  coverage=coverage, span=span, rollup=rollup)


# ─── 후보 수집과 순위 ────────────────────────────────────────────────────
# 파일명 끝에 붙는 언어 태그: ko, en, ko-KR, kor, zh-Hans …
_LANG_TAG = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,4})?$")
# 강제 자막임을 파일명이 밝히는 관례(yt-dlp·리핑 도구 공통).
_FORCED = re.compile(r"(?:^|[.\-_])forced(?:[.\-_]|$)", re.IGNORECASE)


def format_of(path: Path) -> str | None:
    """확장자 → 포맷 이름. 모르는 확장자면 None."""
    return FORMATS.get(path.suffix.lower())


def language_of(path: Path, prefix: str | None = None) -> str | None:
    """파일명이 밝히는 언어 코드. `영상.ko.srt` → "ko", `영상.srt` → None.

    돌려주는 코드는 형식만 통일한다(`영상.KO.srt` → "ko" — lang.normalize).
    `ko`를 `kor`로 바꾸거나 그 반대로 고쳐 쓰지는 않는다: 그 필드는 파일명이 무엇을
    **선언했는가**의 기록이고, 표준 사이의 변환에는 대조표가 필요하다(stt/lang.py).

    prefix는 이 자막이 딸린 **영상 파일명 + "."**이다(sidecar_candidates가 매칭한
    그 접두사). 그것을 벗겨낸 나머지의 첫 마디만 태그로 읽는다. 어간의 마지막
    마디를 그냥 떼면 `강의.mkv.srt`의 "mkv", `강의.avi.srt`의 "avi", `강의.ts.srt`의
    "ts"가 전부 2~3글자라는 이유로 언어가 된다 — `<파일명전체>.srt`는 agent_guide가
    안내하는 배치 형태라 흔하고, 그러면 source.language에 거짓이 실린 채
    사이드카 선택 순위와 --sub-lang 일치 판정이 그 거짓 위에서 돈다.

    prefix를 모르는 호출(--transcript로 지목한 파일·내장 트랙)에서는 옆에 놓인
    영상이 같은 증거가 된다: `강의.mkv.srt` 옆의 `강의.mkv`가 그것이다. 영상마저
    없으면 남은 근거가 이름뿐이라 마지막 마디를 태그로 읽는다(`영상.720p.srt`의
    "720p", `S01E02.srt`처럼 마디가 하나뿐인 이름은 그 자체로 걸러진다)."""
    stem = path.name[:-len(path.suffix)] if path.suffix else path.name
    if prefix is None:
        video = path.with_suffix("")
        prefix = video.name + "." if video.is_file() else ""
    # 어간 끝에 "."을 붙여 비교한다: 접두사가 어간과 정확히 같을 때
    # (`강의.mkv.srt`의 어간 `강의.mkv`와 접두사 `강의.mkv.`) 나머지가 빈 문자열로
    # 떨어져야 "언어 태그 없음"이 된다.
    if prefix and (stem + ".").startswith(prefix):
        tag = (stem + ".")[len(prefix):].split(".", 1)[0]
    else:
        tag = stem.rsplit(".", 1)[1] if "." in stem else ""
    return lang.normalize(tag) if _LANG_TAG.match(tag) else None


# 출처의 등급. 언어가 같은 등급일 때만 여기서 갈린다 — 사이드카가 앞인 근거는
# **의도의 명확함**이다: 영상 옆의 파일은 사용자가 그 자리에 직접 놓은 것이고,
# 내장 트랙은 컨테이너에 묻어 온 것이라(제작자가 넣어 둔 다국어 트랙 전부가
# 늘 거기 있다) 이 실행에서 무엇을 원하는지에 대해 아무 말도 하지 않는다.
SOURCE_ORDER = ("sidecar", "embedded")


@dataclass(frozen=True)
class Candidate:
    """전사 후보 하나 — 사이드카 파일과 내장 트랙을 **같은 모양**으로 세운다.

    두 풀을 한 목록에 담는 것이 이 타입의 존재 이유다. 풀마다 따로 고르고 순서대로
    시도하면(그 전 구조가 그랬다) "사이드카에는 영어만, 내장에는 목표 언어인
    한국어가 있는" 영상에서 영어가 이긴다 — 두 풀을 가로지르는 비교가 없으면
    언어는 풀 **안에서만** 우선이기 때문이다.

    kind는 base.SOURCE_KINDS의 값이라 그대로 result_from_file에 넘어간다.
    label은 사람이 읽을 이름이고 **어느 풀에서 왔는지를 반드시 드러낸다** —
    출처가 섞인 뒤로는 "왜 이것이 뽑혔나"의 답에 출처가 포함되어야 한다.
    notes는 그 후보를 만들며 이미 생긴 사건(내장 트랙 추출 중의 특이사항)이다."""
    kind: str
    path: Path
    format: str
    language: str | None
    label: str
    forced: bool = False
    default: bool = False
    track: int | None = None
    notes: tuple[str, ...] = ()


def _language_rank(declared: str | None, target: str | None) -> int:
    """언어 등급 — ①목표 언어 일치 ②언어 미상 ③그 외.

    불일치는 **탈락이 아니라 순위 하락**이다(등급 2). ko ↔ kor 판정은 표 없이 하는
    근사라(lang.matches) 틀릴 수 있는데, 틀렸다고 후보에서 빼면 사용자가 가진
    유일한 자막이 언어 코드 표기 하나 때문에 사라진다.

    언어 미상이 '그 외'보다 앞인 이유는 두 풀에서 같다: 태그 없는 사이드카는
    사용자가 직접 둔 그 자막이고, 언어를 선언하지 않은 트랙은 대개 그 영상의
    유일한 대사 트랙이다. 목표 언어가 없으면(로케일도 없음) lang.matches가 전부
    False라 자연히 '미상 > 그 외'만 남는다."""
    if lang.matches(declared, target):
        return 0
    return 1 if declared is None else 2


def _rank_key(c: Candidate, target: str | None) -> tuple:
    """후보 하나의 정렬 키. 앞자리일수록 센 기준이다.

    1차가 언어, 2차가 출처인 것이 이 함수의 전부다 — 나머지는 두 풀이 각자 쓰던
    규칙을 그대로 이어받은 꼬리다. 꼬리를 풀별로 갈라 두지 않고 한 튜플로 합칠 수
    있는 이유는, 갈리는 칸이 **풀 안에서 상수**이기 때문이다: 사이드카는 default가
    언제나 False이고 내장 트랙은 forced가 서면 split이 아예 뽑지 않으며 포맷도
    srt 하나다. 상수 칸은 그 풀의 순서를 바꾸지 않으므로, 합친 꼬리는 두 풀의
    기존 순서를 그대로 재현한다(사이드카 forced>포맷>이름, 내장 default>스트림).

    forced가 언어보다 뒤인 것은 이번에 바뀐 자리다. 예전에는 forced가 최우선
    강등이라 '목표 언어의 forced 자막'이 '다른 언어의 정상 자막'에게 졌는데,
    이제 후보는 거부되면 다음 순위로 내려가므로(cli._subtitle_transcript) 진짜
    강제 자막은 커버리지 하한에서 걸러지고 그 자리를 다음 후보가 받는다. 반대로
    이름만 forced인 정상 자막은 언어가 맞는 한 채택되는 것이 옳다.

    타입이 섞이는 칸(track·이름)은 출처 등급이 앞서므로 두 풀 사이에서 비교되지
    않는다 — 튜플 비교는 처음 갈리는 칸에서 끝난다."""
    return (
        _language_rank(c.language, target),
        SOURCE_ORDER.index(c.kind),
        c.forced,
        not c.default,
        FORMAT_ORDER.index(c.format),
        -1 if c.track is None else c.track,
        c.path.name,
    )


def rank(candidates: list[Candidate], target: str | None) -> list[Candidate]:
    """후보를 순위대로 세운다 — 목록 전체를 돌려주는 것이 계약이다.

    1위만 돌려주지 않는 이유: 1위가 검증에서 거부되면(롤업·커버리지) 호출자는
    그다음을 시도해야 한다. 최선 하나만 주면 거부된 순간 남은 후보가 사라져
    사다리가 whisper로 곧장 떨어진다."""
    return sorted(candidates, key=lambda c: _rank_key(c, target))


def rank_rule(target: str | None) -> str:
    """순위 규칙을 사람이 읽을 한 줄로. _rank_key와 같은 순서로 적는다 —
    산출물의 설명과 실제 정렬이 갈리면 그 메모는 거짓말이 된다."""
    want = f"목표 언어 '{target}' 일치 > " if target else ""
    return (f"{want}언어 미상 > 그 외, 사이드카 > 내장 트랙, "
            f"forced 최후, 기본 트랙 > 포맷 {'>'.join(FORMAT_ORDER)} > 스트림·이름 순")


def choice_notes(chosen: Candidate, ranked: list[Candidate],
                 target: str | None) -> list[str]:
    """채택한 후보를 **왜** 골랐는지. 후보가 여럿일 때만 남긴다(하나면 고를 것이 없다).

    forced 경고는 후보 수와 무관하다: 순위에서 최후로 밀렸어도 후보가 그것뿐이면
    채택되는데, 그때 위 메모는 생기지 않으므로 강제 자막을 썼다는 사실이 산출물
    어디에도 남지 않는다. 거부까지 하지 않는 이유는 내장 트랙과 신호의 성질이
    다르기 때문이다 — 컨테이너의 forced 비트는 제작자가 선언한 성질이지만 이쪽은
    파일명 관례일 뿐이라, 이름에 forced가 든 정상 자막을 거부하면 사용자가 유일하게
    가진 자막을 이름 때문에 잃는다. 진짜 강제 자막은 커버리지 하한이 받아 준다."""
    notes = []
    if len(ranked) > 1:
        others = ", ".join(c.label for c in ranked if c is not chosen)
        notes.append(f"자막 후보 {len(ranked)}개 중에서 골랐습니다: {chosen.label} "
                     f"({rank_rule(target)} / 나머지: {others})")
    if chosen.forced:
        notes.append(f"{chosen.label}: 파일명이 forced를 밝히고 있습니다 — "
                     "외국어 대사·간판만 옮긴 일부 구간만 담고 있을 수 있습니다")
    return notes


def sidecar_candidates(video: Path) -> list[Candidate]:
    """영상 옆의 자막 파일들을 후보로 세운다(순위는 매기지 않는다 — rank의 몫).

    **`<어간>.<확장자>`만 보면 가장 흔한 경우를 통째로 놓친다.** yt-dlp의 기본
    출력이 `영상.mp4` + `영상.ko.srt`라 언어 코드가 사이에 끼기 때문이다.
    `영상.mp4.srt`처럼 전체 파일명 뒤에 붙이는 도구도 있어 그것도 받는다.

    이름으로 거르는 것은 여기까지다. 자동 생성 자막은 이름이 수동 자막과 같아서
    (yt-dlp의 --write-subs와 --write-auto-subs가 같은 이름을 쓴다) 여기서 가려낼
    수 없고, 그건 evaluate의 롤업 검사가 맡는다."""
    directory = video.parent
    if not directory.is_dir():
        return []
    # 긴 접두사(전체 파일명)를 먼저 본다. `강의.mkv.srt`에서 짧은 `강의.`를 먼저
    # 벗기면 남는 "mkv"가 언어 태그로 읽힌다 — language_of는 벗겨낸 나머지만 본다.
    prefixes = (video.name + ".", video.stem + ".")
    candidates = []
    for entry in sorted(directory.iterdir(), key=lambda p: p.name):
        fmt = format_of(entry)
        prefix = next((p for p in prefixes if entry.name.startswith(p)), None)
        if fmt is None or prefix is None or not entry.is_file():
            continue
        candidates.append(Candidate(
            kind="sidecar", path=entry, format=fmt,
            language=language_of(entry, prefix),
            label=f"사이드카 자막 '{entry.name}'",
            forced=bool(_FORCED.search(entry.stem))))
    return candidates


def embedded_candidates(tracks: list[dict]) -> tuple[list[Candidate], list[str]]:
    """split이 뽑아 둔 내장 자막 트랙들 → (후보, 후보가 되지 못한 사유).

    tracks의 열두 칸은 split.extract_subtitles가 **전부** 채운다(그 독스트링이
    목록이다). 게이트를 통과한 state.json이면 여기 오는 엔트리도 그 모양이므로
    칸의 유무가 아니라 값만 본다 — .get으로 눅여 두면 split이 칸을 하나 빠뜨린 날
    그 사실이 "자막 트랙이 없다"는 조용한 오답으로 둔갑한다.

    못 뽑은 트랙을 후보에 넣지 않고 사유만 돌려주는 이유: 후보는 **열어 볼 수 있는
    것**의 목록이고(그래야 순위 키의 포맷 칸이 언제나 성립한다), 사유는 그것과
    무관하게 남아야 한다. 열거에서 지우면 "이 영상에는 강제 자막밖에 없었다"가
    어디에도 남지 않아 whisper가 돈 이유를 사후에 설명할 수 없다."""
    if not tracks:
        return [], ["컨테이너 안에 쓸 수 있는 자막 트랙이 없습니다"]
    candidates, notes = [], []
    for entry in tracks:
        label = f"내장 자막 트랙 {entry['track']}({entry['codec']})"
        if entry["skipped"] or not entry["path"]:
            notes.append(f"{label}: {entry['skipped'] or '추출된 파일이 없습니다'}")
            continue
        # 언어는 컨테이너가 선언한 값이다. 형식만 통일해 두는 이유는 채택 시
        # source.language를 이 값으로 덮기 때문 — 'KOR'로 적은 트랙만 대문자로
        # 남으면 기록이 갈린다(형식 통일은 build_source가 하는 일이다).
        # forced는 여기까지 온 트랙에서는 언제나 False다(split이 그 비트가 서면
        # 추출하지 않는다). 그래도 지어내지 않고 선언된 값을 그대로 싣는다 —
        # 순위는 값을 보고 정하지, 어느 풀에서 왔는지로 가정하지 않는다.
        candidates.append(Candidate(
            kind="embedded", path=Path(entry["path"]), format=entry["format"],
            language=lang.normalize(entry["language"]), label=label,
            forced=entry["forced"], default=entry["default"],
            track=entry["track"], notes=tuple(entry["notes"])))
    return candidates, notes


# ─── 결과 조립 ───────────────────────────────────────────────────────────
def result_from_cues(cues: list[Cue], duration: float, *, kind: str, fmt: str,
                     path: Path | None = None, track: int | None = None,
                     language: str | None = None, notes: list[str] | None = None
                     ) -> tuple[dict | None, list[str]]:
    """검증을 통과하면 transcript.json 본체, 아니면 (None, 사유가 담긴 메모).

    채택 여부만 돌려주고 **폴백할지 멈출지는 정하지 않는다** — 명시 지정(--transcript)은
    조용히 넘어가면 안 되고 사이드카·내장 트랙은 넘어가야 하는데, 그 분기는
    사다리를 아는 호출자(cli.run_transcribe)의 몫이다.

    words는 언제나 빈 배열이다. 자막의 시각은 큐 단위로 사람이 맞춘 것이라
    단어 단위로 쪼갤 근거가 없고, 억지로 나누면 있지도 않은 정밀도를 꾸며낸다."""
    notes = list(notes or [])
    report = evaluate(cues, duration)
    if not report.ok:
        notes.append(report.reason)
        return None, notes

    segments = [{"start": round(c.start, 3), "end": round(c.end, 3), "text": c.text}
                for c in cues]
    # 경로는 절대경로로 적는다 — 산출물을 나중에 읽는 쪽은 실행 당시의 작업
    # 디렉터리를 모르므로 상대경로는 어느 파일이었는지 되짚을 수 없다.
    source = build_source(kind, path=str(path.resolve()) if path is not None else None,
                          track=track, format=fmt, language=language,
                          n_cues=report.n_cues, coverage=report.coverage,
                          span=report.span, notes=notes)
    result = build_result(" ".join(c.text for c in cues), segments, [],
                          backend="subtitle", device="none", model=fmt, source=source)
    return result, notes


def result_from_file(path: Path, duration: float, *, kind: str
                     ) -> tuple[dict | None, list[str]]:
    """자막 파일 하나를 읽어 전사 결과로 만든다 — 사다리의 세 자막 단계
    (--transcript·사이드카·split이 뽑아 둔 내장 트랙)가 공유하는 진입점이다.

    읽기·해독 실패도 예외가 아니라 메모로 돌려준다. 사이드카 단계에서는 폴백해야
    하고, 명시 지정에서는 호출자가 이 메모를 그대로 CliError 메시지에 실으면 된다.

    언어는 파일명에서만 읽는다(language_of). 내장 트랙은 컨테이너가 선언한 언어가
    따로 있어 호출자가 그것으로 덮는다 — 뽑아 둔 subs/track{n}.srt의 이름에는
    그 사실이 없다."""
    fmt = format_of(path)
    if fmt is None:
        return None, [(f"지원하지 않는 자막 확장자입니다: {path.suffix or '(없음)'} "
                       f"(가능: {', '.join(sorted(FORMATS))})")]
    try:
        data = path.read_bytes()
    except OSError as e:
        return None, [f"자막 파일을 읽지 못했습니다: {e}"]

    text, encoding = decode_bytes(data)
    notes = [] if encoding.startswith("utf-8") else [f"{encoding} 인코딩으로 읽었습니다"]
    cues, parse_notes = parse(text, fmt)
    return result_from_cues(cues, duration, kind=kind, fmt=fmt, path=path,
                            language=language_of(path), notes=notes + parse_notes)
