"""허브 창 — 세션의 루트 창. 언어 선택, 창 열기/닫기 토글, 레이아웃 저장/복원, 상태 표시.

이 창을 닫으면 전체 애플리케이션이 종료된다(수명주기 루트).

언어 선택이 여기 있는 이유: 허브는 세션에 단 하나뿐이고 항상 떠 있는 창이라,
어느 창을 보고 있든 돌아올 자리가 정해져 있다. 자식 창마다 두면 같은 설정이
여섯 군데에 생긴다.

허브는 이 앱이 띄운 창들 **사이에서만** 최상위다 — 아래 `_raise_above_siblings`
참조. 시스템 전역 최상위는 요구가 아니다(브라우저·에디터 위로 뜨면 안 된다).
"""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QGuiApplication
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from .. import i18n, origin
from ..i18n import tr
from ..session import REGISTRY, Session, window_label

# 출처 줄의 자리 — 원본(웹이면 URL) · 영상 파일 · 자막
ROW_ORIGIN, ROW_VIDEO, ROW_SUBTITLE = range(3)


class _CopyLabel(QLabel):
    """폭에 맞춰 가운데를 줄이는 한 줄 레이블 — 클릭하면 전체 문자열을 알린다.

    가운데 줄임인 이유: 경로도 URL도 정보가 **양 끝**에 있다. 앞은 어느
    디렉터리·도메인인지, 뒤는 파일명·페이지 id다. 오른쪽만 줄이면 같은 폴더의
    파일들이 전부 똑같은 줄로 보인다.

    가로 크기 정책이 Ignored인 이유: QLabel의 sizeHint는 문자열 전체 폭이라 긴
    절대경로 하나가 그대로 창의 최소 폭이 된다 — 허브(최소 340px)가 경로 길이만큼
    넓어지고 사용자가 다시 줄일 수 없게 된다. 폭은 레이아웃이 정하고, 이쪽은 받은
    폭에 맞춰 줄인다.
    """

    clicked = Signal()

    def __init__(self):
        super().__init__()
        self._full = ""
        self._copyable = False
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def full_text(self) -> str:
        return self._full

    def set_content(self, full: str, tip: str, copyable: bool) -> None:
        self._full = full
        self._copyable = copyable
        self.setToolTip(tip)
        # 누를 수 있다는 것이 보여야 누른다 — 아무 표시 없는 레이블은 아무도 누르지
        # 않는다. 커서 모양이 그 자리에서 바로 보이는 유일한 힌트다.
        self.setCursor(Qt.CursorShape.PointingHandCursor if copyable
                       else Qt.CursorShape.ArrowCursor)
        self._elide()

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._elide()

    def _elide(self) -> None:
        fm = QFontMetrics(self.font())
        self.setText(fm.elidedText(self._full, Qt.TextElideMode.ElideMiddle,
                                   max(self.contentsRect().width(), 0)))

    def mouseReleaseEvent(self, ev) -> None:
        # 눌렀다가 밖에서 떼면 취소 — 버튼과 같은 관례라야 오조작을 되돌릴 수 있다
        if (self._copyable and ev.button() == Qt.MouseButton.LeftButton
                and self.rect().contains(ev.position().toPoint())):
            self.clicked.emit()
        super().mouseReleaseEvent(ev)


class _SourceRow:
    """출처 한 줄 — [이름] [URL 또는 경로] [그 자리로 가는 버튼].

    세 줄이 같은 규칙(축약·툴팁·클릭 복사·비활성 사유)으로 움직여야 해서 한 곳에
    둔다. 줄마다 따로 짜면 규칙이 곧 갈라진다.
    격자에 직접 붙는 이유는 이름·값·버튼의 세로줄을 맞추기 위해서다 — 줄마다 독립
    위젯이면 이름 길이가 다른 만큼 값의 시작점이 들쭉날쭉해진다.
    """

    def __init__(self, grid: QGridLayout, row: int, on_copy):
        self._name = QLabel()
        self._value = _CopyLabel()
        self._button = QPushButton()
        self._title = ""
        self._target: tuple[str, object] | None = None
        self._value.clicked.connect(
            lambda: on_copy(self._title, self._value.full_text()))
        self._button.clicked.connect(self._go)
        grid.addWidget(self._name, row, 0)
        grid.addWidget(self._value, row, 1)
        grid.addWidget(self._button, row, 2)
        self.hide()

    def hide(self) -> None:
        for w in (self._name, self._value, self._button):
            w.setVisible(False)

    def set_url(self, title: str, url: str) -> None:
        """웹 원본 — 버튼은 브라우저를 연다."""
        self._fill(title, url, ("url", url), tr("hub.loc.open_url"),
                   blocked=None, note=None)

    def set_file(self, title: str, path: Path, note: str | None = None) -> None:
        """로컬 파일 — 버튼은 파일 관리자에서 그 파일을 드러낸다.

        파일이 사라졌으면 갈 곳이 없다: 버튼을 잠그고 사유를 붙인다. 경로 자체는
        그대로 보여준다 — 어디에 있었는지가 곧 되찾을 단서이고, 복사도 그대로 된다.
        """
        exists = path.exists()
        self._fill(title, str(path), ("file", path) if exists else None,
                   tr(origin.REVEAL_LABEL_KEY),
                   blocked=None if exists else tr("hub.loc.gone"), note=note)

    def set_blocked(self, title: str, text: str, reason: str) -> None:
        """가리킬 자리가 아예 없는 줄 — 사정을 적고 버튼은 사유와 함께 잠근다.

        복사도 막는다: 여기 있는 것은 위치가 아니라 설명 문장이라 붙여 넣을 곳이 없다.
        """
        self._fill(title, text, None, tr("hub.loc.open_url"),
                   blocked=reason, note=None, copyable=False)

    def _fill(self, title: str, value: str, target, button_text: str, *,
              blocked: str | None, note: str | None, copyable: bool = True) -> None:
        self._title = title
        self._target = target
        self._name.setText(tr("hub.loc.name", name=title))
        tip = [value, note, tr("hub.loc.copy_hint") if copyable else None]
        self._value.set_content(value, "\n".join(t for t in tip if t), copyable)
        self._button.setText(button_text)
        self._button.setEnabled(target is not None)
        # 켜져 있으면 "어디로 데려가는지", 잠겼으면 "왜 잠겼는지"
        self._button.setToolTip(blocked or value)
        for w in (self._name, self._value, self._button):
            w.setVisible(True)

    def _go(self) -> None:
        kind, target = self._target   # 대상이 없으면 버튼이 잠겨 있어 여기 못 온다
        if kind == "url":
            origin.open_url(target)
        else:
            origin.reveal(target)


class HubWindow(QWidget):
    def __init__(self, session: Session):
        super().__init__()
        self.session = session
        self.setMinimumWidth(340)

        layout = QVBoxLayout(self)
        source = QGridLayout()
        source.setColumnStretch(1, 1)   # 남는 폭은 전부 경로 몫
        self._rows = [_SourceRow(source, i, self._on_copy) for i in range(3)]
        layout.addLayout(source)
        self._url, self._resolver_missing = self._resolve_url()
        layout.addLayout(self._build_language())
        layout.addWidget(self._build_units())

        self._windows_box = QGroupBox()
        grid = QGridLayout(self._windows_box)
        self._checks: dict[str, QCheckBox] = {}
        for i, (wid, _key) in enumerate(REGISTRY):
            cb = QCheckBox()
            cb.toggled.connect(lambda on, wid=wid: self._on_toggle(wid, on))
            grid.addWidget(cb, i // 2, i % 2)
            self._checks[wid] = cb
        layout.addWidget(self._windows_box)

        row = QHBoxLayout()
        self._save_btn = QPushButton()
        self._save_btn.clicked.connect(session.save_layout)
        self._restore_btn = QPushButton()
        self._restore_btn.clicked.connect(session.restore_layout)
        self._help_btn = QPushButton()
        self._help_btn.clicked.connect(session.show_shortcut_help)
        for b in (self._save_btn, self._restore_btn, self._help_btn):
            row.addWidget(b)
        layout.addLayout(row)

        self._status = QLabel()
        self._status.setTextFormat(Qt.TextFormat.RichText)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        session.windowsChanged.connect(self._sync_checks)
        session.languageChanged.connect(self.retranslate)
        session.store.reloaded.connect(self._update_status)
        session.store.reloaded.connect(self._sync_units)
        # 자막을 갈아 끼워 다시 전사하면 state.json이 바뀐다 — 출처 줄도 따라간다
        session.store.reloaded.connect(self._sync_source)

        # 형제 창 위 유지 — 트리거가 둘인 이유는 서로를 메우기 때문이다.
        #  ① windowsChanged: 창이 새로 열리면 그 창이 앞으로 나온다. show() 직후에
        #     동기적으로 올려 두면 기동(restore_layout)처럼 활성화가 안 걸리는
        #     경로에서도 허브가 덮이지 않는다.
        #  ② focusWindowChanged: 창 활성화가 플랫폼 이벤트로 늦게 도착하면 ①의
        #     올림이 무효가 된다(그 뒤에 창이 앞으로 나온다). 실제로 형제 창이
        #     키를 잡는 순간은 여기서만 잡힌다 — 사용자가 창을 옮겨 다니는
        #     평상시 경로가 이쪽이다.
        session.windowsChanged.connect(self._raise_above_siblings)
        QApplication.instance().focusWindowChanged.connect(self._on_focus_window_changed)

        self.retranslate()
        self._sync_checks()

    # ---------- 창 순서 ----------

    def _on_focus_window_changed(self, win) -> None:
        """형제 창이 포커스를 잡은 순간에만 허브를 올린다.

        `win`이 None인 경우(=포커스가 다른 앱으로 넘어감)를 반드시 걸러야 한다.
        그때 올리면 브라우저·에디터 위로 허브가 튀어나온다.

        "세션 장부에 있는 창인가"로 판정하는 것이 곧 예외 처리다. 장부에 없는
        창 위로는 올라가지 않으므로:
        - 앱 모달(단축키 도움말 QMessageBox) 위로 올라가는 사고가 없다. 모달을
          덮으면 클릭이 전부 막혀 아무것도 할 수 없게 된다.
        - 콤보박스 드롭다운 같은 팝업도 그대로 둔다.
        - 허브 자신도 장부에 없으니 재진입(올림 → 포커스 변화 → 다시 올림)이
          성립하지 않는다. 별도의 재귀 방지 플래그가 필요 없는 이유이며,
          `raise_()`가 포커스를 건드리지 않으므로 애초에 이 시그널이 다시 돌지도
          않는다(깜빡임·포커스 싸움 없음).
        """
        if win is None:
            return
        if any(w.windowHandle() is win for w in self.session.windows.values()):
            self._raise_above_siblings()

    def _raise_above_siblings(self) -> None:
        """포커스는 그대로 두고 창 순서만 올린다.

        `activateWindow()`는 부르지 않는다 — 플레이어에서 스크럽하거나 비교 창에
        허용오차를 입력하는 도중 포커스가 허브로 끌려가면 그 창을 쓸 수 없다.
        `raise_()`는 스택 순서만 바꾸고 키 포커스는 옮기지 않는다.

        버린 후보:
        - `Qt.WindowStaysOnTopHint`: 시스템 전역 최상위라 이 앱이 비활성일 때도
          브라우저·에디터 위에 남는다. 요구는 "이 앱의 창들 사이에서만".
          앱 활성/비활성에 맞춰 플래그를 껐다 켜는 변형도 안 된다 — 보이는 창의
          `setWindowFlags`는 창을 숨겼다 다시 `show()`해야 하고, 그 `show()`가
          포커스를 가져간다.
        - `Qt.Tool`: macOS에서 NSPanel(floating level)이 되어 앱이 비활성이면
          통째로 숨는다. `WA_MacAlwaysShowToolWindow`로 숨김을 끄면 이번엔 다른 앱
          위로 뜬다 — 어느 쪽도 요구와 맞지 않는다. 부모 없는 Tool 창의 on-top은
          Windows·Linux에서 보장되지도 않고, 제목표시줄이 유틸리티 모양으로 바뀌어
          "닫으면 앱이 종료되는 루트 창"이라는 위상과도 어긋난다.
        - 형제 창들에게 허브를 부모로 주기: Qt에서 부모가 있는 창은 부모 **위에**
          뜬다. 방향이 정반대라 오히려 허브가 맨 아래로 간다.
        """
        self.raise_()

    # ---------- 출처 ----------

    def _resolve_url(self) -> tuple[str | None, bool]:
        """원본 URL을 한 번만 해석한다 — (URL, 해석기 없음).

        영상 파일은 세션 내내 바뀌지 않고 해석은 파일을 여는 일이라(info.json 읽기
        또는 컨테이너 메타데이터), 산출물이 갱신될 때마다 다시 물으면 파일 감시가
        울릴 때마다 디스크를 한 번씩 더 건드리게 된다.

        ImportError는 코어에 출처 해석기가 없다는 뜻이다(GUI의 코어 의존은 하한만
        걸려 있어 조합이 성립한다). 이것을 'URL 없음'으로 뭉개면 사용자는 다운로드한
        파일 쪽을 의심하게 되므로, 갈라서 들고 화면에도 다르게 낸다.
        """
        video, _subtitle = origin.source_files(self.session.root,
                                               self.session.video_path)
        if not video.exists():
            # URL은 파일 **옆에서** 읽는다(사이드카 info.json / 컨테이너 메타데이터).
            # 원본이 옮겨졌으면 읽을 것이 애초에 없고, 없는 파일을 해석기에 넘기면
            # 그쪽 예외로 허브가 아예 안 뜬다 — 여기서 묻지 않는 것이 맞다.
            return None, False
        try:
            return origin.source_url(video), False
        except ImportError:
            return None, True

    def _sync_source(self) -> None:
        """이 분석이 무엇에서 나왔는지 — 원본(웹이면 URL) · 영상 파일 · 자막.

        URL이 잡히면 영상 파일 줄이 따로 생긴다. 한 줄에 둘을 겹쳐 놓으면 웹에서
        받아온 영상의 로컬 파일에 닿을 길이 허브에서 사라진다. 반대로 URL이 없으면
        원본이 곧 그 파일이므로 같은 것을 두 줄로 보여주지 않는다.

        자막 줄은 기록이 있을 때만 나온다 — 어느 자막으로 전사했는지는 결과를 읽는
        데 필요한 사실이지만(전사 사다리가 어디서 멈췄는지가 그것으로 갈린다),
        자막 없이 돌린 분석에 빈 줄을 남겨 둘 이유는 없다.
        """
        video, subtitle = origin.source_files(self.session.root,
                                              self.session.video_path)
        if self._url is not None:
            self._rows[ROW_ORIGIN].set_url(tr("hub.loc.origin"), self._url)
            self._rows[ROW_VIDEO].set_file(tr("hub.loc.video_file"), video)
        elif self._resolver_missing:
            self._rows[ROW_ORIGIN].set_blocked(tr("hub.loc.origin"),
                                               tr("hub.loc.no_resolver"),
                                               tr("hub.loc.no_resolver"))
            self._rows[ROW_VIDEO].set_file(tr("hub.loc.video_file"), video)
        else:
            self._rows[ROW_ORIGIN].set_file(tr("hub.loc.origin"), video,
                                            note=tr("hub.loc.no_url"))
            self._rows[ROW_VIDEO].hide()
        if subtitle is None:
            self._rows[ROW_SUBTITLE].hide()
        else:
            self._rows[ROW_SUBTITLE].set_file(tr("hub.loc.subtitle"), subtitle)

    def _on_copy(self, title: str, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self._flash(tr("hub.loc.copied", name=title))

    def _flash(self, message: str) -> None:
        """하단 상태 줄에 잠깐 알린다.

        모달은 쓰지 않는다 — 복사는 되돌릴 것이 없는 동작인데 확인 클릭을 강요한다.
        전용 위젯을 하나 더 두지도 않는다: 비어 있는 동안에도 자리를 차지해 뜰
        때마다 아래 내용이 밀린다. 상태 줄은 이미 "지금 이 세션이 어떤 상태인가"가
        나오는 자리이고, 그 내용(단위·개수)은 언제든 다시 계산할 수 있으므로
        잠깐 빌렸다 되돌린다.
        타이머에 self를 컨텍스트로 준다 — 창이 먼저 닫히면 콜백이 배달되지 않는다.
        """
        self._status.setText(message)
        QTimer.singleShot(2000, self, self._update_status)

    # ---------- 언어 ----------

    def _build_language(self) -> QHBoxLayout:
        """언어 목록은 항상 원어 표기로 둔다 — 지금 UI를 못 읽는 사용자야말로
        이 콤보를 써야 하는 사람이라, 현재 언어로 번역해 두면 자기 언어를 못 찾는다."""
        row = QHBoxLayout()
        self._lang_label = QLabel()
        row.addWidget(self._lang_label)
        self._lang_combo = QComboBox()
        for code, native in i18n.LANGUAGES:
            self._lang_combo.addItem(native, code)
        self._lang_combo.setCurrentIndex(self._lang_combo.findData(i18n.current()))
        self._lang_combo.currentIndexChanged.connect(self._on_language_pick)
        row.addWidget(self._lang_combo)
        row.addStretch(1)
        return row

    def _on_language_pick(self, _index: int) -> None:
        self.session.set_language(self._lang_combo.currentData())

    # ---------- 분석 단위 ----------

    def _build_units(self) -> QGroupBox:
        """분석 단위 선택 — `--range`를 여러 번 주면 독립 결과물이 그만큼 생긴다.
        구간이 겹치면 같은 시각도 단위마다 다르게 보이므로, 무엇을 보고 있는지
        항상 드러나 있어야 한다. 전환은 데이터만 갈아끼우고 창들은 따라온다."""
        self._units_box = QGroupBox()
        col = QVBoxLayout(self._units_box)
        self._unit_combo = QComboBox()
        self._unit_combo.currentTextChanged.connect(self._on_unit_pick)
        col.addWidget(self._unit_combo)
        self._unit_note = QLabel()
        self._unit_note.setStyleSheet("color:gray;")
        self._unit_note.setWordWrap(True)
        col.addWidget(self._unit_note)
        return self._units_box

    def _sync_units(self) -> None:
        st = self.session.store
        entries = st.available_units()
        self._unit_combo.blockSignals(True)
        self._unit_combo.clear()
        for e in entries:
            rng = e.get("range")
            span = (tr("hub.unit_span_full") if rng is None
                    else tr("hub.unit_span_range", start=rng[0], end=rng[1]))
            self._unit_combo.addItem(tr("hub.unit_item", name=e["name"], span=span),
                                     e["name"])
        if st.unit is not None:
            i = self._unit_combo.findData(st.unit)
            if i >= 0:
                self._unit_combo.setCurrentIndex(i)
        self._unit_combo.blockSignals(False)
        self._unit_combo.setEnabled(len(entries) > 1)
        if len(entries) > 1:
            self._unit_note.setText(tr("hub.unit_note_many"))
        elif entries:
            self._unit_note.setText(tr("hub.unit_note_one"))
        else:
            self._unit_note.setText(tr("hub.unit_note_none"))

    def _on_unit_pick(self, _text: str) -> None:
        name = self._unit_combo.currentData()
        if name:
            self.session.set_unit(name)

    # ---------- 창 ----------

    def _on_toggle(self, wid: str, on: bool) -> None:
        if on:
            self.session.open_window(wid)
        else:
            self.session.close_window(wid)

    def _sync_checks(self) -> None:
        for wid, cb in self._checks.items():
            cb.blockSignals(True)
            cb.setChecked(wid in self.session.windows)
            cb.blockSignals(False)

    # ---------- 표시 ----------

    def retranslate(self) -> None:
        self.setWindowTitle(tr("hub.title", name=self.session.video_path.name))
        self._sync_source()
        self._lang_label.setText(tr("hub.language"))
        # 선택은 콤보 밖(설정 복원·다른 창)에서도 바뀔 수 있다 — 현재 언어를 되비춘다.
        # 항목 이름 자체는 원어 표기라 다시 채울 것이 없다.
        self._lang_combo.blockSignals(True)
        self._lang_combo.setCurrentIndex(self._lang_combo.findData(i18n.current()))
        self._lang_combo.blockSignals(False)
        self._units_box.setTitle(tr("hub.units_group"))
        self._windows_box.setTitle(tr("hub.windows_group"))
        self._save_btn.setText(tr("hub.save_layout"))
        self._restore_btn.setText(tr("hub.restore_layout"))
        self._help_btn.setText(tr("hub.shortcuts"))
        for wid, cb in self._checks.items():
            cb.setText(window_label(wid))
        self._sync_units()
        self._update_status()

    def _update_status(self) -> None:
        st = self.session.store
        if st.metadata:
            self._status.setText(tr(
                "hub.status", unit=st.unit, start=st.window[0], end=st.window[1],
                screens=len(st.screens), frames=len(st.frames),
                rejected=len(st.rejected), segments=len(st.segments)))
        else:
            self._status.setText(tr("hub.status_none"))

    def closeEvent(self, ev) -> None:
        # QApplication은 허브보다 오래 산다 — 끊지 않으면 종료 중에도 포커스 변경이
        # 배달되어, 이미 파괴된 위젯을 건드리며 RuntimeError가 난다.
        # 실패해도 아래 종료 절차까지 막으면 안 되므로 삼킨다(닫기 재진입 등).
        try:
            QApplication.instance().focusWindowChanged.disconnect(
                self._on_focus_window_changed)
        except (RuntimeError, TypeError):
            pass
        self.session.save_layout()
        self.session.shutdown()
        super().closeEvent(ev)
