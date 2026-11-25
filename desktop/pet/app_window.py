"""Native Alex desktop UI. All text is rendered as text, all turns use Controller."""
from __future__ import annotations
import os
from PySide6.QtCore import Qt, QTimer, QRectF, Signal, QEvent, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter, QKeySequence, QShortcut, QIcon
from PySide6.QtWidgets import QMainWindow, QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit, QScrollArea, QCheckBox, QSizePolicy, QStackedWidget, QGraphicsOpacityEffect
from .config import ROOT
from .robot_head import RobotHeadAnimation
STYLE = '\nQMainWindow { background: #f4f8f6; }\nQWidget { font-family: "Segoe UI"; font-size: 14px; color: #203d40; }\nQFrame#sidebar { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #17484a,stop:1 #102e36); border: none; }\nQFrame#sidebar QLabel { color: #e1f4ef; background: transparent; }\nQLabel#brand { font-size: 32px; font-weight: 700; color: white; }\nQLabel#eyebrow { font-size: 11px; font-weight: 600; color: #8dbbb5; }\nQLabel#sideNote { font-size: 12px; color: #a2c4bf; }\nQLabel#heading { font-size: 25px; font-weight: 650; color: #173a3d; }\nQLabel#muted { color: #637c7e; font-size: 12px; }\nQLabel#status { background: #e0f1eb; color: #186a5f; border: 1px solid #cbe6dc; border-radius: 15px; padding: 7px 13px; font-size: 12px; }\nQLabel#status[phase="thinking"] { background: #f7efd9; color: #826329; border-color: #ebdfbf; }\nQLabel#status[phase="speaking"] { background: #dff1ef; color: #176b70; border-color: #c3e3df; }\nQLabel#status[phase="error"] { background: #fff0eb; color: #a2493b; border-color: #edc9bf; }\nQPushButton { background: #ffffff; border: 1px solid #dbe5e2; border-radius: 10px; padding: 10px 15px; text-align: left; }\nQPushButton:hover { background: #edf6f2; border-color: #85b9ad; }\nQPushButton:pressed { background: #d6eae3; }\nQPushButton:disabled { color: #91a2a1; background: #edf0ef; border-color: #e0e6e3; }\nQPushButton#nav { background: transparent; color: #e0f1ed; border: none; padding: 12px 14px; }\nQPushButton#nav:hover { background: #285055; }\nQPushButton#nav:checked { background: #2b5557; color: #d7fff1; border-left: 3px solid #83d6bd; border-radius: 10px; }\nQPushButton#newChat { background: #bce5d5; color: #123c39; border: none; font-weight: 600; }\nQPushButton#primary { background: #0c7d72; color: white; border: none; font-weight: 600; text-align: center; }\nQPushButton#primary:hover { background: #09665e; }\nQPushButton#primary:disabled { background: #b7d2ca; color: #f8fbfa; }\nQPushButton#stop { color: #a34e40; border: 1px solid #e4c9c2; background: #fff9f6; }\nQPushButton#mic[active="true"] { color: #056b5f; background: #dcf2e9; border-color: #69ab99; }\nQFrame#composer { background: white; border: 1px solid #cadfd7; border-radius: 18px; }\nQPlainTextEdit { background: transparent; border: none; padding: 6px; font-size: 15px; color: #203d40; selection-background-color: #bee3d7; }\nQScrollArea { border: none; background: transparent; }\nQWidget#conversation { background: transparent; }\nQFrame#userBubble { background: #d8eee5; border: 1px solid #cce7da; border-radius: 17px; }\nQFrame#alexBubble { background: white; border: 1px solid #dfeae5; border-radius: 17px; }\nQLabel#message { background: transparent; border: none; font-size: 15px; }\nQLabel#role { background: transparent; border: none; font-size: 11px; font-weight: 600; color: #62847d; }\nQFrame#welcome { border: 1px solid #d0e9df; background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #e3f4ed,stop:1 #f3faf6); border-radius: 22px; }\nQLabel#welcomeTitle { font-size: 26px; font-weight: 650; }\nQCheckBox { spacing: 7px; font-size: 12px; color: #607a77; }\nQScrollBar:vertical { border: none; background: transparent; width: 7px; margin: 2px; }\nQScrollBar::handle:vertical { background: #b7ccc4; min-height: 30px; border-radius: 3px; }\nQScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }\n'

def label(text, name='', wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget

def button(text, callback, name=''):
    widget = QPushButton(text)
    widget.setObjectName(name)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.clicked.connect(callback)
    return widget

class Composer(QPlainTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (not event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            if not event.isAutoRepeat():
                self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)

class Avatar(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.robot = RobotHeadAnimation(ROOT / 'assets/robot-heads')
        self.setFixedSize(128, 156)
        self.timer = QTimer(self)
        self.timer.setInterval(max(50, round(1000 / max(1, getattr(self.robot, 'fps', 10)))))
        self.timer.timeout.connect(self.update)

    def showEvent(self, event):
        self.robot.suspend(False)
        self.timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        self.robot.suspend(True)
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.robot.paint(painter, QRectF(14, 41, 100, 100)):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor('#55b7a5'))
            painter.drawEllipse(18, 34, 90, 90)
            painter.setBrush(QColor('#163d43'))
            painter.drawEllipse(41, 67, 8, 11)
            painter.drawEllipse(78, 67, 8, 11)
        painter.end()

class Message(QFrame):

    def __init__(self, role, text):
        super().__init__()
        self.setObjectName('userBubble' if role == 'Bạn' else 'alexBubble')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 13, 18, 15)
        layout.setSpacing(7)
        layout.addWidget(label(role.upper(), 'role'))
        self.content = label(text, 'message', True)
        self.content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.content)
        self._entrance = None

    def animate_entrance(self):
        """Fade a new bubble once; never reanimate streaming text updates."""
        if self._entrance is not None:
            return
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b'opacity', self)
        self._entrance = animation
        animation.setDuration(180)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(self._finish_entrance)
        animation.start()

    def _finish_entrance(self):
        animation = self._entrance
        if animation is None:
            return
        self._entrance = None
        animation.setTargetObject(None)
        self.setGraphicsEffect(None)
        animation.deleteLater()

class AlexAppWindow(QMainWindow):

    def __init__(self, engine, pet):
        super().__init__()
        self.engine, self.pet = (engine, pet)
        self.setWindowTitle('Alex — Trợ lý của bạn')
        app_icon = ROOT / 'assets/alex-desktop.ico'
        self.setWindowIcon(QIcon(str(app_icon)) if app_icon.is_file() else pet.windowIcon())
        self.resize(1120, 780)
        self.setMinimumSize(800, 580)
        self.setStyleSheet(STYLE)
        self.pending = False
        self.resetting = False
        self.echo_pending = False
        self.last_target = None
        self.current_user = self.current_answer = None
        self.message_rows = []
        self._space_fullscreen = False
        self._space_previous_state = Qt.WindowState.WindowNoState
        self._center_fullscreen = False
        self._center_previous_state = Qt.WindowState.WindowNoState
        self.center_page = self.space_page = None
        self.current_mode, self.current_caption = ('paused', '')
        self._build()
        engine.transcript.connect(self._question)
        engine.reply.connect(self._reply)
        engine.state.connect(self._state)
        engine.desktop_finished.connect(self._finished)
        engine.finished.connect(lambda: self._state('error', 'Bộ xử lý Alex đã dừng. Bạn mở lại Alex nhé.'))
        self.poll = QTimer(self)
        self.poll.setInterval(500)
        self.poll.timeout.connect(self._sync)
        shortcut = QShortcut(QKeySequence('Ctrl+L'), self)
        shortcut.activated.connect(self.editor.setFocus)
        escape = QShortcut(QKeySequence('Escape'), self)
        escape.activated.connect(self._escape)
        self.center_fullscreen_key = QShortcut(QKeySequence(Qt.Key.Key_QuoteLeft), self)
        self.center_fullscreen_key.setAutoRepeat(False)
        self.center_fullscreen_key.setEnabled(False)
        self.center_fullscreen_key.activated.connect(self._toggle_center_fullscreen)
        self._sync()

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame()
        self.sidebar = sidebar
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(220)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(22, 30, 22, 24)
        side.setSpacing(13)
        side.addWidget(label('ALEX', 'brand'))
        side.addWidget(label('NGƯỜI BẠN TRÊN LAPTOP', 'eyebrow'))
        side.addSpacing(20)
        self.new_button = button('+  Trò chuyện mới', self._new_chat, 'newChat')
        side.addWidget(self.new_button)
        self.chat_nav = button('Trò chuyện', lambda: self._show_page('chat'), 'nav')
        self.chat_nav.setCheckable(True)
        self.chat_nav.setChecked(True)
        side.addWidget(self.chat_nav)
        self.center_nav = button('Trạm chỉ huy', lambda: self._show_page('center'), 'nav')
        self.center_nav.setCheckable(True)
        side.addWidget(self.center_nav)
        self.space_nav = button('Vũ trụ Alex', lambda: self._show_page('space'), 'nav')
        self.space_nav.setCheckable(True)
        side.addWidget(self.space_nav)
        side.addSpacing(8)
        self.pet_button = button('Hiện pet trên màn hình', self._toggle_pet, 'nav')
        self.pet_button.hide()
        side.addStretch()
        self.avatar = Avatar()
        side.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignHCenter)
        side.addWidget(label('Một Alex, hai cách trò chuyện.', '', True))
        side.addWidget(label('Dùng cửa sổ này hoặc gọi pet. Cả hai cùng làm việc với bạn.', 'sideNote', True))
        side.addSpacing(10)
        side.addWidget(label('Ctrl + Space   •   Bật / ẩn pet', 'sideNote'))
        layout.addWidget(sidebar)
        self.pages = QStackedWidget()
        self._page_overlay = QLabel(self.pages)
        self._page_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._page_overlay.setScaledContents(True)
        self._page_overlay.hide()
        self._page_opacity = QGraphicsOpacityEffect(self._page_overlay)
        self._page_overlay.setGraphicsEffect(self._page_opacity)
        self._page_transition = QPropertyAnimation(self._page_opacity, b'opacity', self)
        self._page_transition.setDuration(210)
        self._page_transition.setStartValue(1.0)
        self._page_transition.setEndValue(0.0)
        self._page_transition.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._page_transition.finished.connect(self._clear_page_transition)
        self.pages.installEventFilter(self)
        self.chat_page = QWidget()
        main = QVBoxLayout(self.chat_page)
        main.setContentsMargins(30, 26, 30, 20)
        main.setSpacing(16)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(label('Trò chuyện với Alex', 'heading'))
        titles.addWidget(label('Hỏi một điều, hoặc nhờ mình làm trên máy tính.', 'muted'))
        header.addLayout(titles, 1)
        self.status = label('Đang khởi động', 'status')
        header.addWidget(self.status, 0, Qt.AlignmentFlag.AlignTop)
        main.addLayout(header)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.conversation = QWidget()
        self.conversation.setObjectName('conversation')
        self.messages = QVBoxLayout(self.conversation)
        self.messages.setContentsMargins(0, 10, 10, 8)
        self.messages.setSpacing(16)
        self.welcome = QFrame()
        self.welcome.setObjectName('welcome')
        welcome = QVBoxLayout(self.welcome)
        welcome.setContentsMargins(28, 28, 28, 28)
        welcome.setSpacing(14)
        welcome.addWidget(label('Chào bạn, mình là Alex.', 'welcomeTitle', True))
        welcome.addWidget(label('Bạn muốn làm gì hôm nay?\nMình có thể trò chuyện, mở ứng dụng và giúp bạn điều khiển laptop.', '', True))
        for title, query in [('Mở YouTube', 'Mở YouTube cho tôi'), ('Mở thư mục HỌC TẬP', 'Mở thư mục HỌC TẬP cho tôi'), ('Xem giờ trên laptop', 'Bây giờ là mấy giờ?')]:
            welcome.addWidget(button(title + '  →', lambda checked=False, q=query: self._suggest(q)))
        self.messages.addWidget(self.welcome)
        self.messages.addStretch(1)
        self.scroll.setWidget(self.conversation)
        main.addWidget(self.scroll, 1)
        self.notice = label('Hội thoại chỉ giữ trong phiên. Bạn có thể bắt đầu bằng chữ hoặc bật mic.', 'muted', True)
        self.notice.setMinimumHeight(32)
        main.addWidget(self.notice)
        composer = QFrame()
        composer.setObjectName('composer')
        compose = QVBoxLayout(composer)
        compose.setContentsMargins(12, 9, 12, 12)
        compose.setSpacing(4)
        self.editor = Composer()
        self.editor.setPlaceholderText('Nhắn cho Alex…')
        self.editor.setAccessibleName('Câu hỏi gửi Alex')
        self.editor.setFixedHeight(84)
        self.editor.submitted.connect(self._send)
        compose.addWidget(self.editor)
        controls = QHBoxLayout()
        self.mic_button = button('Bật mic', self._toggle_mic, 'mic')
        self.mic_button.setToolTip('Dùng mic của pet. Alex tự nhận câu khi bạn nói xong.')
        controls.addWidget(self.mic_button)
        self.speak = QCheckBox('Đọc câu trả lời khi gõ')
        self.speak.setChecked(False)
        controls.addWidget(self.speak)
        controls.addStretch()
        self.stop_button = button('Dừng', self._stop, 'stop')
        controls.addWidget(self.stop_button)
        self.send_button = button('Gửi  ↑', self._send, 'primary')
        self.send_button.setMinimumWidth(92)
        controls.addWidget(self.send_button)
        compose.addLayout(controls)
        main.addWidget(composer)
        main.addWidget(label('Enter để gửi  ·  Shift + Enter xuống dòng  ·  Ctrl + L nhập câu hỏi', 'muted'))
        self.pages.addWidget(self.chat_page)
        from PySide6.QtWidgets import QApplication
        layout.addWidget(self.pages, 1)

    def _show_page(self, name):
        if name != 'space' and self._space_fullscreen:
            self._set_space_fullscreen(False)
        if name != 'center' and self._center_fullscreen:
            self._set_center_fullscreen(False)
        if name == 'center' and self.center_page is None:
            from .command_center import CommandCenter
            self.center_page = CommandCenter()
            self.center_page.chat_requested.connect(lambda: self._show_page('chat'))
            self.center_page.space_requested.connect(lambda: self._show_page('space'))
            self.center_page.mic_requested.connect(self._toggle_mic)
            self.center_page.stop_requested.connect(self._stop)
            self.center_page.command_requested.connect(self._suggest)
            self.center_page.fullscreen_requested.connect(self._toggle_center_fullscreen)
            if self.current_answer:
                self.center_page.latest.setText(self.current_answer.content.text()[:240])
            self.pages.addWidget(self.center_page)
        if name == 'space' and self.space_page is None:
            from .space_view import SpacePage
            self.space_page = SpacePage()
            self.space_page.fullscreen_requested.connect(self._toggle_space_fullscreen)
            self.pages.addWidget(self.space_page)
        target = {'chat': self.chat_page, 'center': self.center_page, 'space': self.space_page}[name]
        changing = self.pages.currentWidget() is not target
        snapshot = None
        if changing and self.isVisible() and (not self.isMinimized()):
            self._page_transition.stop()
            snapshot = self.pages.grab()
        self.pages.setCurrentWidget(target)
        self.center_fullscreen_key.setEnabled(name == 'center')
        if name == 'center':
            from .command_center import SIDEBAR_STYLE
            self.sidebar.setStyleSheet(SIDEBAR_STYLE)
        else:
            self.sidebar.setStyleSheet('')
        for key, nav in [('chat', self.chat_nav), ('center', self.center_nav), ('space', self.space_nav)]:
            nav.setChecked(key == name)
        self.avatar.setVisible(name == 'chat')
        if name == 'chat':
            self.editor.setFocus()
        if changing and snapshot is not None and (not snapshot.isNull()):
            self._page_overlay.setGeometry(self.pages.rect())
            self._page_overlay.setPixmap(snapshot)
            self._page_opacity.setOpacity(1.0)
            self._page_overlay.show()
            self._page_overlay.raise_()
            self._page_transition.start()
        self._sync()

    def _toggle_space_fullscreen(self):
        self._set_space_fullscreen(not self._space_fullscreen)

    def _set_space_fullscreen(self, enabled):
        if enabled == self._space_fullscreen:
            return
        if enabled:
            if self.space_page is None or self.pages.currentWidget() is not self.space_page:
                return
            self._space_previous_state = self.windowState()
            self._space_sidebar_visible = not self.sidebar.isHidden()
            self._space_pet_was_visible = self.pet.isVisible()
            self._space_fullscreen = True
            if self._space_pet_was_visible:
                self.pet.setVisible(False)
            self.sidebar.hide()
            self.space_page.fullscreen_button.setText('Thoát toàn màn hình')
            self.space_page.set_immersive(True)
            self.showFullScreen()
        else:
            self._space_fullscreen = False
            self.space_page.fullscreen_button.setText('Toàn màn hình')
            self.space_page.set_immersive(False)
            if self._space_pet_was_visible and (not self.pet.isVisible()):
                self.pet.setVisible(True)
            self.sidebar.setVisible(self._space_sidebar_visible)
            state = self._space_previous_state
            if state & Qt.WindowState.WindowFullScreen:
                self.showFullScreen()
            elif state & Qt.WindowState.WindowMaximized:
                self.showMaximized()
            else:
                self.showNormal()

    def _toggle_center_fullscreen(self):
        self._set_center_fullscreen(not self._center_fullscreen)

    def _set_center_fullscreen(self, enabled):
        if enabled == self._center_fullscreen:
            return
        if enabled:
            if self.center_page is None or self.pages.currentWidget() is not self.center_page:
                return
            self._center_previous_state = self.windowState()
            self._center_sidebar_visible = not self.sidebar.isHidden()
            self._center_fullscreen = True
            if self.engine.paused.is_set():
                self._toggle_mic()
            self.sidebar.hide()
            self.center_page.set_immersive(True)
            self.showFullScreen()
            self._sync()
        else:
            self._center_fullscreen = False
            self.engine.paused.set()
            mic = getattr(self.engine, 'mic', None)
            if mic is not None:
                mic.gate(False)
            self.notice.setText('Mic đã tắt.')
            if self.center_page is not None:
                self.center_page.set_immersive(False)
            self.sidebar.setVisible(getattr(self, '_center_sidebar_visible', True))
            state = self._center_previous_state
            if state & Qt.WindowState.WindowFullScreen:
                self.showFullScreen()
            elif state & Qt.WindowState.WindowMaximized:
                self.showMaximized()
            else:
                self.showNormal()
            self._sync()

    def _escape(self):
        if self._space_fullscreen:
            self._set_space_fullscreen(False)
        elif self._center_fullscreen:
            self._set_center_fullscreen(False)
        else:
            self._stop()

    def _clear_page_transition(self):
        self._page_overlay.hide()
        self._page_overlay.clear()

    def eventFilter(self, watched, event):
        if watched is self.pages and event.type() == QEvent.Type.Resize:
            self._page_transition.stop()
            self._clear_page_transition()
        return super().eventFilter(watched, event)

    def _remember_target(self):
        if os.name != 'nt':
            return
        try:
            from .window_actions import Windows
            api = Windows()
            target = api.identity(api.foreground())
            if target and target[1] != os.getpid() and api.visible(target[0]) and api.enabled(target[0]) and (target[3] not in {'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd', '#32770'}):
                self.last_target = target
        except OSError:
            pass

    def show_app(self):
        self._remember_target()
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.editor.setFocus()

    def _suggest(self, text):
        self._show_page('chat')
        self.editor.setPlainText(text)
        self._send()

    def _send(self):
        if self.pending:
            return
        text = self.editor.toPlainText().strip()
        if not text:
            return
        error = self.engine.submit_text(text, self.speak.isChecked(), self.last_target)
        if error:
            self.notice.setText(error)
            return
        self.pending = True
        self.echo_pending = True
        self.current_user = self._add_message('Bạn', text)
        self.current_answer = None
        self.editor.clear()
        self.notice.setText('Đã nhận câu hỏi. Bạn có thể bấm Dừng để ngắt.')
        self._sync()

    def _question(self, text):
        if self.echo_pending and self.current_user:
            self.current_user.content.setText(text)
            self.echo_pending = False
        else:
            self.current_user = self._add_message('Bạn', text)
        self.current_answer = None

    def _reply(self, text):
        if self.center_page is not None:
            self.center_page.latest.setText(text[:240])
        if self.current_answer is None:
            self.current_answer = self._add_message('Alex', text)
        else:
            bar = self.scroll.verticalScrollBar()
            follow = bar.maximum() - bar.value() < 90
            self.current_answer.content.setText(text)
            if follow:
                QTimer.singleShot(0, self._bottom)

    def _add_message(self, role, text):
        self.welcome.hide()
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        message = Message(role, text)
        if role == 'Bạn':
            line.addSpacing(64)
        line.addWidget(message, 1)
        if role != 'Bạn':
            line.addSpacing(24)
        self.messages.insertWidget(self.messages.count() - 1, row)
        self.message_rows.append(row)
        if self.isVisible() and (not self.isMinimized()) and (self.pages.currentWidget() is self.chat_page):
            message.animate_entrance()
        while len(self.message_rows) > 60:
            old = self.message_rows.pop(0)
            self.messages.removeWidget(old)
            old.deleteLater()
        QTimer.singleShot(0, self._bottom)
        return message

    def _bottom(self):
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _state(self, mode, caption):
        self.current_mode, self.current_caption = (mode, caption)
        names = {'thinking': 'Đang xử lý', 'speaking': 'Đang nói', 'listening': 'Đang nghe', 'idle': 'Sẵn sàng', 'paused': 'Sẵn sàng · mic tắt', 'error': 'Cần kiểm tra'}
        self.status.setText(names.get(mode, 'Alex'))
        if self.status.property('phase') != mode:
            self.status.setProperty('phase', mode)
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
        self.avatar.robot.set_state(mode)
        if mode == 'error':
            self.notice.setText(caption)
        self._sync()

    def _finished(self, ok, message):
        if self.resetting and ok:
            for row in self.message_rows:
                self.messages.removeWidget(row)
                row.deleteLater()
            self.message_rows.clear()
            self.current_user = self.current_answer = None
            self.welcome.show()
            if self.center_page is not None:
                self.center_page.latest.setText('Trò chuyện mới đã sẵn sàng.')
        elif not ok and self.pending:
            if self.current_answer is None:
                self._reply(message)
        self.pending = self.resetting = self.echo_pending = False
        self.notice.setText(message)
        self._sync()

    def _sync(self):
        ready = self.engine.desktop_ready.is_set() and self.engine.isRunning()
        busy = self.engine.busy.is_set() or self.pending
        self.send_button.setEnabled(ready and (not busy))
        self.new_button.setEnabled(ready and (not busy))
        self.stop_button.setEnabled(busy or self._scrolling())
        self.mic_button.setEnabled(ready and (not busy))
        active = not self.engine.paused.is_set()
        self.mic_button.setText('Tắt mic' if active else 'Bật mic')
        if self.mic_button.property('active') != active:
            self.mic_button.setProperty('active', active)
            self.mic_button.style().unpolish(self.mic_button)
            self.mic_button.style().polish(self.mic_button)
        self.pet_button.setText('Ẩn pet trên màn hình' if self.pet.isVisible() else 'Hiện pet trên màn hình')
        if self.center_page is not None:
            self.center_page.sync(ready, busy, active, self.current_mode, self.current_caption)
        if self.isVisible():
            self._remember_target()

    def _scrolling(self):
        scroller = getattr(self.engine, 'web_scroller', None)
        return bool(scroller and scroller.is_active())

    def _stop(self):
        busy = self.pending or self.engine.busy.is_set()
        if busy or self._scrolling():
            self.engine.interrupt()
            self.notice.setText('Đang dừng yêu cầu…' if busy else 'Đã dừng lướt web.')
            self._sync()

    def _new_chat(self):
        self._show_page('chat')
        error = self.engine.submit_text('', reset=True)
        if error:
            self.notice.setText(error)
            return
        self.pending = self.resetting = True
        self._sync()

    def _toggle_mic(self):
        self.engine.toggle()
        self.notice.setText('Mic đã tắt.' if self.engine.paused.is_set() else 'Mic đang bật. Bạn nói câu hỏi; Alex nhận câu khi bạn nói xong.')
        self._sync()

    def _toggle_pet(self):
        self.pet.setVisible(not self.pet.isVisible())
        self._sync()

    def showEvent(self, event):
        self.poll.start()
        self._sync()
        super().showEvent(event)

    def hideEvent(self, event):
        self.poll.stop()
        self._page_transition.stop()
        self._clear_page_transition()
        super().hideEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, 'pages'):
            active = self.isVisible() and (not self.isMinimized())
            if not active:
                self._page_transition.stop()
                self._clear_page_transition()
            for page in (self.center_page, self.space_page):
                if page is not None:
                    page.set_active(active and self.pages.currentWidget() is page)
            if self.pages.currentWidget() is self.chat_page:
                self.avatar.robot.suspend(not active)
                self.avatar.timer.start() if active else self.avatar.timer.stop()
            self.poll.start() if active else self.poll.stop()
        super().changeEvent(event)

    def closeEvent(self, event):
        if self._space_fullscreen:
            self._set_space_fullscreen(False)
        if self._center_fullscreen:
            self._set_center_fullscreen(False)
        event.ignore()
        self.hide()

def pet_callback(pet, name):
    return lambda: getattr(pet, name)()
