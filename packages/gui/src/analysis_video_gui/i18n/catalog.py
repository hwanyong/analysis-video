"""문자열 카탈로그 — 키 하나에 세 언어를 나란히.

언어별 파일로 쪼개지 않은 이유: 이 규모(≈180키)에서는 옆에 나란히 있어야
번역 누락과 뜻이 갈라진 문장이 눈에 띈다. 파일이 갈리면 키는 세 곳에서
따로 늙는다.

값에 HTML이 섞인 항목이 있다. 마크업이 문장 구조(강조·색·줄바꿈)와 붙어
있어서 떼면 번역자가 어순을 못 바꾼다 — 문장의 일부로 함께 둔다.
자리표시자는 `str.format` 규칙이며, 언어마다 순서를 바꿔도 된다.
"""

CATALOG: dict[str, dict[str, str]] = {

    # ---------- 기동 (app.py) ----------
    "app.description": {
        "ko": "analysis-video 산출물 검토·교정 GUI (허브 + 독립 멀티 윈도우)",
        "en": "Review/correct analysis-video outputs (hub + independent windows)",
        "ja": "analysis-video 成果物の検証・修正 GUI (ハブ + 独立マルチウィンドウ)",
    },
    "app.arg.path": {
        "ko": "원본 비디오 파일 또는 .analysis 디렉토리",
        "en": "Source video file, or an .analysis directory",
        "ja": "元の動画ファイル、または .analysis ディレクトリ",
    },
    "app.err.no_state": {
        "ko": "오류: {out_dir}에 state.json이 없습니다 — analysis-video로 먼저 분석하세요",
        "en": "Error: no state.json in {out_dir} — run analysis-video on it first",
        "ja": "エラー: {out_dir} に state.json がありません — 先に analysis-video で解析してください",
    },
    "app.err.schema": {
        "ko": "오류: {out_dir}의 분석 형식이 이 버전과 맞지 않습니다 "
              "(필요: {expected} / 발견: {found}) — 새 디렉토리에 다시 분석하세요",
        "en": "Error: the analysis in {out_dir} is not in this version's format "
              "(need {expected}, found {found}) — re-run the analysis into a new directory",
        "ja": "エラー: {out_dir} の解析形式がこのバージョンと一致しません "
              "(必要: {expected} / 検出: {found}) — 新しいディレクトリで解析し直してください",
    },
    "app.err.source_missing": {
        "ko": "오류: state.json의 원본 비디오를 찾을 수 없습니다: {src}",
        "en": "Error: source video from state.json not found: {src}",
        "ja": "エラー: state.json の元動画が見つかりません: {src}",
    },
    "app.err.no_file": {
        "ko": "오류: 파일이 없습니다: {path}",
        "en": "Error: no such file: {path}",
        "ja": "エラー: ファイルがありません: {path}",
    },
    "app.warn.no_outputs": {
        "ko": "경고: {out_dir}에 분석 산출물 없음 — 플레이어만 유효합니다 "
              "(frames 스테이지를 먼저 실행하세요)",
        "en": "Warning: no analysis outputs in {out_dir} — only the player will work "
              "(run the frames stage first)",
        "ja": "警告: {out_dir} に解析成果物がありません — プレーヤーのみ利用できます "
              "(先に frames ステージを実行してください)",
    },

    # ---------- 창 이름 (session.REGISTRY) ----------
    "win.player": {"ko": "① 플레이어", "en": "① Player", "ja": "① プレーヤー"},
    "win.frame_sync": {"ko": "② 프레임 싱크", "en": "② Frame sync", "ja": "② フレーム同期"},
    "win.dialogue": {"ko": "③ 대사 싱크", "en": "③ Dialogue sync", "ja": "③ 台詞同期"},
    "win.timeline": {"ko": "④ 타임라인", "en": "④ Timeline", "ja": "④ タイムライン"},
    "win.gallery": {"ko": "⑤ 갤러리", "en": "⑤ Gallery", "ja": "⑤ ギャラリー"},
    "win.compare": {"ko": "⑥ 비교 리포트", "en": "⑥ Compare report", "ja": "⑥ 比較レポート"},

    # ---------- 마크 종류 (session.MARK_KINDS) ----------
    "mark.frame": {"ko": "채택 프레임", "en": "Kept frames", "ja": "採用フレーム"},
    "mark.rejected": {"ko": "탈락 후보", "en": "Rejected", "ja": "却下候補"},
    "mark.screen": {"ko": "화면 시작", "en": "Screen starts", "ja": "画面開始"},
    "mark.flag": {"ko": "GT 플래그", "en": "GT flags", "ja": "GT フラグ"},
    "mark.requested": {"ko": "주문 추출", "en": "Requested", "ja": "指定抽出"},
    "mark.transition": {"ko": "전환 구간", "en": "Transitions", "ja": "遷移区間"},
    "mark.segment": {"ko": "STT 세그먼트", "en": "STT segments", "ja": "STT セグメント"},
    "mark.described": {
        "ko": "{label} {index}/{total} · t={time:.2f}",
        "en": "{label} {index}/{total} · t={time:.2f}",
        "ja": "{label} {index}/{total} · t={time:.2f}",
    },

    # ---------- 검출 근거 (metadata의 sources) ----------
    # 값 자체는 파이프라인이 정한 식별자다. GUI는 이미 색·정렬 순서로 이들의
    # 표현을 소유하고 있으므로(SOURCE_COLORS/SOURCE_ORDER) 표시명도 여기서 준다.
    # 반면 reject_reason은 `blank(<=0.002)`처럼 값이 조립된 진단 코드라 GUI가
    # 문자열을 파싱해야 번역할 수 있다 — 그 결합을 만들지 않고 원문 그대로 둔다.
    "source.screen-start": {"ko": "화면 시작", "en": "screen start", "ja": "画面開始"},
    "source.screen-end": {"ko": "화면 끝", "en": "screen end", "ja": "画面終了"},
    "source.initial": {"ko": "최초 화면", "en": "initial", "ja": "初期画面"},

    # ---------- 허브 ----------
    "hub.title": {
        "ko": "analysis-video 허브 — {name}",
        "en": "analysis-video hub — {name}",
        "ja": "analysis-video ハブ — {name}",
    },
    # 출처 줄 (hub._SourceRow) — 이름·값·버튼이 한 줄을 이룬다
    "hub.loc.name": {"ko": "<b>{name}</b>:", "en": "<b>{name}</b>:",
                     "ja": "<b>{name}</b>:"},
    "hub.loc.origin": {"ko": "원본", "en": "Source", "ja": "元"},
    "hub.loc.video_file": {"ko": "영상 파일", "en": "Video file", "ja": "動画ファイル"},
    "hub.loc.subtitle": {"ko": "자막", "en": "Subtitle", "ja": "字幕"},
    "hub.loc.open_url": {
        "ko": "브라우저에서 열기",
        "en": "Open in browser",
        "ja": "ブラウザで開く",
    },
    # 파일 관리자는 플랫폼마다 이름이 다르고 리눅스에서는 동작 자체가 다르다
    # (파일을 선택해 주지 못하고 폴더만 연다) — 문구도 거기에 맞춘다.
    "hub.loc.reveal_macos": {
        "ko": "Finder에서 보기",
        "en": "Show in Finder",
        "ja": "Finder で表示",
    },
    "hub.loc.reveal_windows": {
        "ko": "탐색기에서 보기",
        "en": "Show in Explorer",
        "ja": "エクスプローラーで表示",
    },
    "hub.loc.reveal_other": {
        "ko": "폴더 열기",
        "en": "Open folder",
        "ja": "フォルダを開く",
    },
    "hub.loc.copy_hint": {
        "ko": "클릭하면 클립보드로 복사됩니다",
        "en": "Click to copy to the clipboard",
        "ja": "クリックするとクリップボードにコピーします",
    },
    # 무엇을 복사했는지만 알린다(줄 이름). 복사한 문자열 자체를 넣으면 긴 경로가
    # 상태 줄을 접어 창 높이가 출렁인다.
    "hub.loc.copied": {
        "ko": "복사됨 — {name}",
        "en": "Copied — {name}",
        "ja": "コピーしました — {name}",
    },
    "hub.loc.gone": {
        "ko": "이 자리에 파일이 없습니다 — 옮겼거나 지웠습니다",
        "en": "No file at this location — moved or deleted",
        "ja": "この場所にファイルがありません — 移動または削除されました",
    },
    "hub.loc.no_url": {
        "ko": "원본 URL은 찾지 못했습니다 — 내려받을 때 yt-dlp의 "
              "--write-info-json 또는 --embed-metadata를 쓰면 파일 옆에 남습니다",
        "en": "No source URL found — download with yt-dlp's --write-info-json or "
              "--embed-metadata to keep it next to the file",
        "ja": "元の URL は見つかりませんでした — ダウンロード時に yt-dlp の "
              "--write-info-json または --embed-metadata を使うとファイルの隣に残ります",
    },
    "hub.loc.no_resolver": {
        "ko": "원본 URL을 확인할 수 없습니다 — 코어(analysis-video)에 출처 해석기가 "
              "없습니다. 코어를 올리세요",
        "en": "Cannot check the source URL — this analysis-video core has no origin "
              "resolver. Upgrade the core",
        "ja": "元の URL を確認できません — コア (analysis-video) に出所リゾルバが "
              "ありません。コアを更新してください",
    },
    "hub.language": {"ko": "언어", "en": "Language", "ja": "言語"},
    "hub.windows_group": {
        "ko": "창 (체크 = 열기)",
        "en": "Windows (checked = open)",
        "ja": "ウィンドウ (チェック = 開く)",
    },
    "hub.save_layout": {"ko": "레이아웃 저장", "en": "Save layout", "ja": "レイアウト保存"},
    "hub.restore_layout": {"ko": "레이아웃 복원", "en": "Restore layout", "ja": "レイアウト復元"},
    "hub.shortcuts": {"ko": "단축키 (?)", "en": "Shortcuts (?)", "ja": "ショートカット (?)"},
    "hub.units_group": {"ko": "분석 단위", "en": "Analysis unit", "ja": "解析単位"},
    "hub.unit_item": {
        "ko": "{name}  ({span})",
        "en": "{name}  ({span})",
        "ja": "{name}  ({span})",
    },
    "hub.unit_span_full": {"ko": "영상 전체", "en": "whole video", "ja": "動画全体"},
    "hub.unit_span_range": {
        "ko": "{start:.1f}~{end:.1f}초",
        "en": "{start:.1f}~{end:.1f}s",
        "ja": "{start:.1f}~{end:.1f}秒",
    },
    "hub.unit_note_many": {
        "ko": "단위는 서로 독립입니다 — 구간이 겹치면 같은 시각도 단위마다 "
              "다르게 나뉠 수 있습니다.",
        "en": "Units are independent — where ranges overlap, the same instant can be "
              "split differently in each unit.",
        "ja": "各単位は互いに独立です — 区間が重なると、同じ時刻でも単位ごとに "
              "違う切れ方になることがあります。",
    },
    "hub.unit_note_one": {
        "ko": "분석 단위가 하나뿐입니다 (CLI에서 --range로 부분 분석을 추가할 수 있습니다).",
        "en": "Only one analysis unit (add partial analyses with --range in the CLI).",
        "ja": "解析単位は 1 つだけです (CLI の --range で部分解析を追加できます)。",
    },
    "hub.unit_note_none": {
        "ko": "분석 단위 없음 — frames를 먼저 실행하세요.",
        "en": "No analysis unit — run frames first.",
        "ja": "解析単位がありません — 先に frames を実行してください。",
    },
    "hub.status": {
        "ko": "단위 <b>{unit}</b> · 구간 {start:.1f}~{end:.1f}초<br>"
              "화면 {screens} · 채택 {frames} / 탈락 {rejected} · 세그먼트 {segments}<br>"
              "<span style='color:gray'>산출물 변경 감시 중 — CLI 재분석 시 자동 갱신</span>",
        "en": "Unit <b>{unit}</b> · range {start:.1f}~{end:.1f}s<br>"
              "screens {screens} · kept {frames} / rejected {rejected} · "
              "segments {segments}<br>"
              "<span style='color:gray'>Watching outputs — refreshes automatically when "
              "the CLI re-analyzes</span>",
        "ja": "単位 <b>{unit}</b> · 区間 {start:.1f}~{end:.1f}秒<br>"
              "画面 {screens} · 採用 {frames} / 却下 {rejected} · セグメント {segments}<br>"
              "<span style='color:gray'>成果物を監視中 — CLI の再解析で自動更新</span>",
    },
    "hub.status_none": {
        "ko": "<span style='color:#c60'>metadata.json 없음 — frames 스테이지를 먼저 "
              "실행하세요 (플레이어만 사용 가능)</span>",
        "en": "<span style='color:#c60'>No metadata.json — run the frames stage first "
              "(only the player is usable)</span>",
        "ja": "<span style='color:#c60'>metadata.json がありません — 先に frames ステージを "
              "実行してください (プレーヤーのみ利用可)</span>",
    },

    # ---------- 단축키 도움말 ----------
    "help.title": {
        "ko": "키보드 단축키",
        "en": "Keyboard shortcuts",
        "ja": "キーボードショートカット",
    },
    "help.body": {
        "ko": """\
[재생]                              [마크로 정확히 이동]
Space / K      재생 · 일시정지          ↓ / ↑      다음/이전 마크 (켜 둔 종류 전부)
← / →          5초 뒤로/앞으로          N / ⇧N     다음/이전 채택 프레임
J / L          10초 뒤로/앞으로         G / ⇧G     다음/이전 GT 플래그
, / .          프레임 단위 스텝
⇧, / ⇧.        배속 내림/올림           R          탈락 후보 숨김/표시
0~9            0~90% 지점으로 점프      F          GT 플래그 추가/제거(토글)
Home/End       처음/끝                  ?          이 도움말
M              음소거

↓/↑가 훑는 종류는 타임라인 범례의 체크박스로 고릅니다(STT 세그먼트는 수백 건이라
기본 제외). 타임라인 클릭도 가까운 마크에 달라붙고, 점프하면 화면 밖으로 나간
재생 커서를 뷰포트가 따라갑니다.

GT 플래그 = "이 장면은 반드시 뽑혔어야 한다"는 사람의 정답 표시. 로직 검출과
대조해 ⑥ 비교 리포트가 recall(놓친 것)·precision(군더더기)을 계산합니다.
같은 자리에서 F를 다시 누르거나 타임라인의 ▼를 ⇧클릭하면 취소됩니다.

플레이어 슬라이더·타임라인은 드래그하는 동안 화면이 실시간으로 따라옵니다.
타임라인 전용:  V 스크럽 · H 이동 · Z 확대 도구 / Space 홀드+드래그 = 임시 이동
                휠 = 확대·축소 (도구 막대의 배율 슬라이더·＋－·⤢ 전체 보기)""",
        "en": """\
[Playback]                             [Jump precisely to marks]
Space / K      Play / pause            ↓ / ↑      Next/prev mark (every enabled kind)
← / →          Back / forward 5s       N / ⇧N     Next/prev kept frame
J / L          Back / forward 10s      G / ⇧G     Next/prev GT flag
, / .          Step one frame
⇧, / ⇧.        Speed down / up         R          Hide/show rejected candidates
0~9            Jump to 0~90% point     F          Add/remove GT flag (toggle)
Home/End       Start / end             ?          This help
M              Mute

Which kinds ↓/↑ sweeps is chosen by the checkboxes in the timeline legend (STT
segments run to the hundreds, so they are off by default). Clicking the timeline
also snaps to the nearest mark, and after a jump the viewport follows a playhead
that scrolled out of view.

GT flag = a human marking "this scene had to be extracted". The ⑥ compare report
matches them against the detector to compute recall (what was missed) and
precision (what was superfluous). Press F again at the same spot, or ⇧-click the
▼ in the timeline, to undo one.

The player slider and the timeline scrub live — the picture follows while you drag.
Timeline only:  V scrub · H pan · Z zoom tool / hold Space + drag = temporary pan
                wheel = zoom in/out (toolbar has a zoom slider, ＋－, ⤢ fit all)""",
        "ja": """\
[再生]                              [マークへ正確に移動]
Space / K      再生・一時停止           ↓ / ↑      次/前のマーク (有効な種類すべて)
← / →          5秒 戻る/進む            N / ⇧N     次/前の採用フレーム
J / L          10秒 戻る/進む           G / ⇧G     次/前の GT フラグ
, / .          1フレームずつ移動
⇧, / ⇧.        再生速度 下げ/上げ       R          却下候補の非表示/表示
0~9            0~90% 地点へジャンプ     F          GT フラグ 追加/削除(トグル)
Home/End       先頭/末尾                ?          このヘルプ
M              ミュート

↓/↑ がたどる種類はタイムライン凡例のチェックボックスで選びます (STT セグメントは
数百件になるため既定では除外)。タイムラインのクリックも近くのマークに吸着し、
ジャンプで画面外に出た再生カーソルにはビューポートが追従します。

GT フラグ = 「この場面は必ず抽出されるべきだ」という人間の正解。⑥ 比較レポートが
検出結果と突き合わせて recall (取りこぼし)・precision (余分) を算出します。
同じ位置で F をもう一度押すか、タイムラインの ▼ を ⇧クリックすると取り消せます。

プレーヤーのスライダーとタイムラインは、ドラッグ中も映像がリアルタイムで追従します。
タイムライン専用:  V スクラブ · H 移動 · Z 拡大ツール / Space 長押し+ドラッグ = 一時移動
                   ホイール = 拡大・縮小 (ツールバーの倍率スライダー·＋－·⤢ 全体表示)""",
    },

    # ---------- 플레이어 ----------
    "player.slider_tip": {
        "ko": "드래그하면 화면이 실시간으로 따라옵니다",
        "en": "Drag and the picture follows in real time",
        "ja": "ドラッグすると映像がリアルタイムで追従します",
    },
    "player.mute_tip": {"ko": "음소거 (M)", "en": "Mute (M)", "ja": "ミュート (M)"},
    "player.rate_tip": {"ko": "재생 배속 (⇧, / ⇧.)", "en": "Playback speed (⇧, / ⇧.)",
                        "ja": "再生速度 (⇧, / ⇧.)"},

    # ---------- 프레임 싱크 ----------
    "fsync.no_frame": {
        "ko": "이 구간에 채택된 프레임 없음\n(첫 프레임 이전이거나 metadata 없음)",
        "en": "No kept frame for this span\n(before the first frame, or no metadata)",
        "ja": "この区間に採用フレームはありません\n(最初のフレームより前、または metadata なし)",
    },
    "fsync.no_image": {
        "ko": "이미지 파일 없음", "en": "Image file missing", "ja": "画像ファイルがありません",
    },
    "fsync.head": {
        "ko": "<b>t={time}</b> ({clock}) &nbsp; 구간 {start}~{end}초 &nbsp; yavg {yavg}",
        "en": "<b>t={time}</b> ({clock}) &nbsp; span {start}~{end}s &nbsp; yavg {yavg}",
        "ja": "<b>t={time}</b> ({clock}) &nbsp; 区間 {start}~{end}秒 &nbsp; yavg {yavg}",
    },
    "fsync.detected": {
        "ko": "<b>검출:</b> {sources}",
        "en": "<b>Detected by:</b> {sources}",
        "ja": "<b>検出:</b> {sources}",
    },
    "fsync.reason": {
        "ko": "★ <b>reason:</b> {reason}",
        "en": "★ <b>reason:</b> {reason}",
        "ja": "★ <b>reason:</b> {reason}",
    },
    "fsync.trigger_dialogue": {
        "ko": "▸ <b>트리거 대사</b> ({clock}): {text}",
        "en": "▸ <b>Trigger line</b> ({clock}): {text}",
        "ja": "▸ <b>トリガー台詞</b> ({clock}): {text}",
    },
    "fsync.dialogue_count": {
        "ko": "<b>구간 대사:</b> {count}건 — 대사 싱크 창 참조",
        "en": "<b>Lines in span:</b> {count} — see the dialogue sync window",
        "ja": "<b>区間の台詞:</b> {count}件 — 台詞同期ウィンドウを参照",
    },
    "fsync.rejected_head": {
        "ko": "<hr><b>이 구간의 탈락 후보</b> (R로 숨김):",
        "en": "<hr><b>Rejected candidates in this span</b> (R hides them):",
        "ja": "<hr><b>この区間の却下候補</b> (R で非表示):",
    },
    "fsync.rejected_item": {
        "ko": "<span style='color:#a55'>✗ t={time} — {reason}{extra}</span>",
        "en": "<span style='color:#a55'>✗ t={time} — {reason}{extra}</span>",
        "ja": "<span style='color:#a55'>✗ t={time} — {reason}{extra}</span>",
    },

    # ---------- 갤러리 ----------
    "gallery.status": {
        "ko": "프레임 {total}장{suffix} (R: 탈락 포함 토글)",
        "en": "{total} frames{suffix} (R: toggle rejected)",
        "ja": "フレーム {total} 枚{suffix} (R: 却下を含める切替)",
    },
    "gallery.loading": {
        "ko": " — 로딩 {done}/{total}",
        "en": " — loading {done}/{total}",
        "ja": " — 読み込み中 {done}/{total}",
    },

    # ---------- 비교 리포트 ----------
    "compare.tolerance": {"ko": "허용오차(초):", "en": "Tolerance (s):", "ja": "許容誤差(秒):"},
    "compare.tolerance_tip": {
        "ko": "GT 플래그와 검출 프레임을 같은 것으로 볼 시간 오차 (Esc: 편집 종료)",
        "en": "How far apart a GT flag and a detected frame may be and still match "
              "(Esc: leave the field)",
        "ja": "GT フラグと検出フレームを同一とみなす時間差 (Esc: 編集終了)",
    },
    "compare.add_flag": {
        "ko": "현재 시각 플래그 추가/제거 (F)",
        "en": "Add/remove flag at playhead (F)",
        "ja": "現在位置のフラグ 追加/削除 (F)",
    },
    "compare.delete_selected": {"ko": "선택 삭제", "en": "Delete selected", "ja": "選択を削除"},
    "compare.export": {
        "ko": "compare.json 내보내기",
        "en": "Export compare.json",
        "ja": "compare.json を書き出す",
    },
    "compare.col_gt": {"ko": "GT 플래그", "en": "GT flag", "ja": "GT フラグ"},
    "compare.col_detected": {"ko": "매칭 검출", "en": "Matched detection", "ja": "対応する検出"},
    "compare.col_gap": {"ko": "Δ(초)", "en": "Δ (s)", "ja": "Δ(秒)"},
    "compare.col_verdict": {"ko": "판정", "en": "Verdict", "ja": "判定"},
    "compare.summary": {
        "ko": "단위 {unit} ({start:.0f}~{end:.0f}초){scope}<br>"
              "GT {n_flags}개 · 검출 {n_detected}개 &nbsp;|&nbsp; "
              "<b>precision {precision}</b> (검출 중 GT 근방 비율) &nbsp; "
              "<b>recall {recall}</b> (GT 중 검출된 비율)",
        "en": "Unit {unit} ({start:.0f}~{end:.0f}s){scope}<br>"
              "GT {n_flags} · detected {n_detected} &nbsp;|&nbsp; "
              "<b>precision {precision}</b> (detections near a GT flag) &nbsp; "
              "<b>recall {recall}</b> (GT flags that were detected)",
        "ja": "単位 {unit} ({start:.0f}~{end:.0f}秒){scope}<br>"
              "GT {n_flags}件 · 検出 {n_detected}件 &nbsp;|&nbsp; "
              "<b>precision {precision}</b> (検出のうち GT 近傍の割合) &nbsp; "
              "<b>recall {recall}</b> (GT のうち検出された割合)",
    },
    "compare.scope_excluded": {
        "ko": " · 구간 밖 GT {count}개는 제외",
        "en": " · {count} GT flags outside the range excluded",
        "ja": " · 区間外の GT {count}件は除外",
    },
    "compare.tp": {"ko": "TP ✓", "en": "TP ✓", "ja": "TP ✓"},
    "compare.fn": {
        "ko": "FN ✗ (로직이 놓침)",
        "en": "FN ✗ (detector missed it)",
        "ja": "FN ✗ (ロジックが見逃し)",
    },
    "compare.no_gt": {
        "ko": "<span style='color:gray'>이 구간에 GT 플래그가 없습니다 — 영상을 보며 "
              "<b>F</b>로 “여기서 뽑혔어야 한다”를 찍으면 그때부터 precision·recall이 "
              "산출됩니다.</span>",
        "en": "<span style='color:gray'>No GT flags in this range — watch the video and "
              "press <b>F</b> to mark “this had to be extracted”; precision and recall "
              "appear from then on.</span>",
        "ja": "<span style='color:gray'>この区間に GT フラグがありません — 動画を見ながら "
              "<b>F</b> で「ここは抽出されるべきだった」を記録すると、そこから "
              "precision・recall が算出されます。</span>",
    },
    "compare.fp_list": {
        "ko": "<b>GT 없는 검출(FP 후보) {count}건:</b> {shown}{more}",
        "en": "<b>Detections with no GT (FP candidates), {count}:</b> {shown}{more}",
        "ja": "<b>GT のない検出(FP 候補) {count}件:</b> {shown}{more}",
    },
    "compare.fp_more": {
        "ko": " 외 {count}건", "en": " and {count} more", "ja": " ほか {count}件",
    },
    "compare.fp_none": {
        "ko": "GT 없는 검출: 없음",
        "en": "Detections with no GT: none",
        "ja": "GT のない検出: なし",
    },
    "compare.exported": {
        "ko": " &nbsp;<span style='color:#5a5'>→ {name} 저장됨</span>",
        "en": " &nbsp;<span style='color:#5a5'>→ saved {name}</span>",
        "ja": " &nbsp;<span style='color:#5a5'>→ {name} を保存しました</span>",
    },

    # ---------- 타임라인: 레인 눈금 ----------
    "lane.frames": {"ko": "프레임", "en": "frames", "ja": "フレーム"},
    "lane.rejected": {"ko": "탈락", "en": "rejected", "ja": "却下"},
    "lane.requested": {"ko": "주문", "en": "requested", "ja": "指定"},
    "lane.screens": {"ko": "화면", "en": "screens", "ja": "画面"},
    "lane.stt": {"ko": "STT", "en": "STT", "ja": "STT"},
    "lane.flags": {"ko": "플래그", "en": "flags", "ja": "フラグ"},
    "lane.anchor": {"ko": "anchor diff", "en": "anchor diff", "ja": "anchor diff"},
    "lane.rate": {"ko": "순간 변화율", "en": "change rate", "ja": "瞬間変化率"},
    "lane.area": {"ko": "컷 면적", "en": "cut area", "ja": "カット面積"},

    # ---------- 타임라인: 도구 ----------
    "tool.scrub": {"ko": "▶ 스크럽", "en": "▶ Scrub", "ja": "▶ スクラブ"},
    "tool.scrub.hint": {
        "ko": "드래그 = 재생 위치 실시간 이동 · 클릭 = 그 시각으로 점프",
        "en": "Drag = move the playhead live · Click = jump to that instant",
        "ja": "ドラッグ = 再生位置をリアルタイム移動 · クリック = その時刻へジャンプ",
    },
    "tool.pan": {"ko": "✋ 이동", "en": "✋ Pan", "ja": "✋ 移動"},
    "tool.pan.hint": {
        "ko": "드래그 = 상하좌우 이동 · 오른쪽 드래그 = 축 배율",
        "en": "Drag = pan in any direction · Right-drag = scale the axes",
        "ja": "ドラッグ = 上下左右に移動 · 右ドラッグ = 軸の倍率",
    },
    "tool.zoom": {"ko": "🔍 확대", "en": "🔍 Zoom", "ja": "🔍 拡大"},
    "tool.zoom.hint": {
        "ko": "드래그 = 사각 영역만큼 확대 · 오른쪽 드래그 = 축 배율",
        "en": "Drag = zoom to the rectangle · Right-drag = scale the axes",
        "ja": "ドラッグ = 矩形の範囲に拡大 · 右ドラッグ = 軸の倍率",
    },
    "tool.common_hint": {
        "ko": "휠 = 확대·축소 · Space 홀드+드래그 = 임시 이동",
        "en": "Wheel = zoom · Hold Space + drag = temporary pan",
        "ja": "ホイール = 拡大・縮小 · Space 長押し+ドラッグ = 一時移動",
    },
    "tool.space_held": {
        "ko": " · Space 홀드 중", "en": " · Space held", "ja": " · Space 長押し中",
    },
    "tool.button": {"ko": "{label} ({accel})", "en": "{label} ({accel})",
                    "ja": "{label} ({accel})"},

    # ---------- 타임라인: 도구 막대·판독 ----------
    "timeline.zoom": {"ko": "배율", "en": "Zoom", "ja": "倍率"},
    "timeline.zoom_out": {"ko": "축소", "en": "Zoom out", "ja": "縮小"},
    "timeline.zoom_in": {"ko": "확대", "en": "Zoom in", "ja": "拡大"},
    "timeline.fit_all": {"ko": "전체 보기", "en": "Fit all", "ja": "全体表示"},
    "timeline.zoom_slider_tip": {
        "ko": "전체 보기 ↔ 최대 확대",
        "en": "Fit all ↔ maximum zoom",
        "ja": "全体表示 ↔ 最大拡大",
    },
    "timeline.axis_time": {"ko": "시간(초)", "en": "time (s)", "ja": "時間(秒)"},
    "timeline.readout_idle": {
        "ko": "마우스를 올리면 그 시각의 내용이 여기 나옵니다",
        "en": "Hover the graph to read what is at that instant",
        "ja": "グラフにマウスを乗せると、その時刻の内容がここに出ます",
    },
    "timeline.out_of_range": {
        "ko": "영상 범위 밖", "en": "Outside the video", "ja": "動画の範囲外",
    },
    "timeline.hover_frame": {
        "ko": "프레임 #{index} t={time} · {sources}",
        "en": "frame #{index} t={time} · {sources}",
        "ja": "フレーム #{index} t={time} · {sources}",
    },
    "timeline.hover_signals": {
        "ko": "<span style='color:#6af'>anchor {anchor:.4f}</span>{anchor_mark} · "
              "<span style='color:#fa6'>순간 {rate:.6f}</span>{rate_mark} · "
              "<span style='color:#b8f'>면적 {area:.4f}</span>{area_mark}",
        "en": "<span style='color:#6af'>anchor {anchor:.4f}</span>{anchor_mark} · "
              "<span style='color:#fa6'>rate {rate:.6f}</span>{rate_mark} · "
              "<span style='color:#b8f'>area {area:.4f}</span>{area_mark}",
        "ja": "<span style='color:#6af'>anchor {anchor:.4f}</span>{anchor_mark} · "
              "<span style='color:#fa6'>瞬間 {rate:.6f}</span>{rate_mark} · "
              "<span style='color:#b8f'>面積 {area:.4f}</span>{area_mark}",
    },

    # ---------- 타임라인: 범례 ----------
    "timeline.legend_check": {
        "ko": "<span style='color:#888'>체크 = ↓/↑ 순회·클릭 스냅 대상</span>",
        "en": "<span style='color:#888'>Checked = swept by ↓/↑ and snapped to on click"
              "</span>",
        "ja": "<span style='color:#888'>チェック = ↓/↑ の巡回・クリック吸着の対象</span>",
    },
    "timeline.legend_frames": {
        "ko": "<b>프레임 채택 {count}</b>",
        "en": "<b>Frames kept {count}</b>",
        "ja": "<b>採用フレーム {count}</b>",
    },
    "timeline.legend_source": {
        "ko": "&nbsp;{swatch} {label} {count}",
        "en": "&nbsp;{swatch} {label} {count}",
        "ja": "&nbsp;{swatch} {label} {count}",
    },
    "timeline.legend_multi": {
        "ko": "&nbsp;<span style='color:#eee'>▭</span> 흰 테두리 = 복합 근거",
        "en": "&nbsp;<span style='color:#eee'>▭</span> white border = multiple sources",
        "ja": "&nbsp;<span style='color:#eee'>▭</span> 白枠 = 複合根拠",
    },
    "timeline.kind_item": {
        "ko": "{glyph} {label} {count}{extra}",
        "en": "{glyph} {label} {count}{extra}",
        "ja": "{glyph} {label} {count}{extra}",
    },
    "timeline.kind_hidden": {"ko": " · 숨김(R)", "en": " · hidden (R)", "ja": " · 非表示(R)"},
    "timeline.kind_need_at": {
        "ko": " · frame --at", "en": " · frame --at", "ja": " · frame --at",
    },
    "timeline.kind_need_flag": {
        "ko": " · F로 기입", "en": " · press F", "ja": " · F で記録",
    },
    "timeline.legend_gt": {
        "ko": "<span style='color:#888'>GT 플래그 = “이 장면은 뽑혔어야 한다”는 사람의"
              " 정답. F 추가/취소, ▼ ⇧클릭 삭제, G 이동. ⑥ 비교 리포트가 검출과"
              " 대조해 recall·precision을 낸다.</span>",
        "en": "<span style='color:#888'>GT flag = a human marking “this had to be"
              " extracted”. F adds/undoes, ⇧-click a ▼ deletes, G jumps. The ⑥ compare"
              " report scores recall and precision against the detector.</span>",
        "ja": "<span style='color:#888'>GT フラグ = 「ここは抽出されるべきだった」という"
              "人間の正解。F で追加/取消、▼ を ⇧クリックで削除、G で移動。⑥ 比較レポートが"
              "検出と突き合わせて recall・precision を算出する。</span>",
    },
    "timeline.legend_transition": {
        "ko": "<span style='color:#888'>전환 시작 = anchor diff <b>또는</b> 컷 면적이"
              " 기준을 넘을 때. 그 뒤 순간 변화율이 잦아들면 트리거.</span>",
        "en": "<span style='color:#888'>A transition starts when anchor diff <b>or</b>"
              " cut area crosses its baseline. It triggers once the change rate settles"
              " down afterwards.</span>",
        "ja": "<span style='color:#888'>遷移の開始 = anchor diff <b>または</b> カット面積が"
              "基準を超えたとき。その後、瞬間変化率が収まるとトリガー。</span>",
    },
    "timeline.legend_anchor": {
        "ko": "{swatch} anchor diff (앵커와의 거리)",
        "en": "{swatch} anchor diff (distance from the anchor)",
        "ja": "{swatch} anchor diff (アンカーとの距離)",
    },
    "timeline.legend_anchor_thr": {
        "ko": "&nbsp;&nbsp;<span style='color:#f55'>┈</span> {value} <b>넘으면</b> 전환 시작",
        "en": "&nbsp;&nbsp;<span style='color:#f55'>┈</span> <b>above</b> {value} = "
              "transition starts",
        "ja": "&nbsp;&nbsp;<span style='color:#f55'>┈</span> {value} を<b>超えると</b>遷移開始",
    },
    "timeline.legend_rate": {
        "ko": "{swatch} 순간 변화율 (직전 프레임 대비)",
        "en": "{swatch} change rate (against the previous frame)",
        "ja": "{swatch} 瞬間変化率 (直前フレーム比)",
    },
    "timeline.legend_rate_thr": {
        "ko": "&nbsp;&nbsp;<span style='color:#f55'>┈</span> {value} <b>아래로</b> "
              "내려가면 트리거",
        "en": "&nbsp;&nbsp;<span style='color:#f55'>┈</span> <b>below</b> {value} = "
              "triggers",
        "ja": "&nbsp;&nbsp;<span style='color:#f55'>┈</span> {value} を<b>下回ると</b>"
              "トリガー",
    },
    "timeline.legend_area": {
        "ko": "{swatch} 컷 면적 (확 바뀐 픽셀 비율)",
        "en": "{swatch} cut area (share of pixels that changed abruptly)",
        "ja": "{swatch} カット面積 (急変したピクセルの割合)",
    },
    "timeline.legend_area_thr": {
        "ko": "&nbsp;&nbsp;<span style='color:#f55'>┈</span> {value} <b>넘으면</b> 컷",
        "en": "&nbsp;&nbsp;<span style='color:#f55'>┈</span> <b>above</b> {value} = a cut",
        "ja": "&nbsp;&nbsp;<span style='color:#f55'>┈</span> {value} を<b>超えると</b>カット",
    },
    "timeline.no_series": {
        "ko": "<span style='color:#777'>detect_signals.npz 없음 — 변화량 미표시</span>",
        "en": "<span style='color:#777'>No detect_signals.npz — change signals hidden"
              "</span>",
        "ja": "<span style='color:#777'>detect_signals.npz がありません — 変化量は非表示"
              "</span>",
    },

    # ---------- 타임라인: 그래프 위 라벨 ----------
    "timeline.thr_anchor": {
        "ko": "{value} ↑ 넘으면", "en": "{value} ↑ above", "ja": "{value} ↑ 超過",
    },
    "timeline.thr_rate": {
        "ko": "{value} ↓ 내려가면", "en": "{value} ↓ below", "ja": "{value} ↓ 下回る",
    },
    "timeline.thr_area": {
        "ko": "{value} ↑ 넘으면 컷", "en": "{value} ↑ above = cut", "ja": "{value} ↑ 超過でカット",
    },
    "timeline.flag_tip": {
        "ko": "GT {clock}{note}  (⇧클릭 = 삭제)",
        "en": "GT {clock}{note}  (⇧-click = delete)",
        "ja": "GT {clock}{note}  (⇧クリック = 削除)",
    },
    "timeline.rejected_tip": {
        "ko": "t={time} {reason}", "en": "t={time} {reason}", "ja": "t={time} {reason}",
    },
    "timeline.jumped": {
        "ko": "<span style='color:#8cf'>▸ {description}</span>",
        "en": "<span style='color:#8cf'>▸ {description}</span>",
        "ja": "<span style='color:#8cf'>▸ {description}</span>",
    },
}
