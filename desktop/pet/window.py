from __future__ import annotations
import logging
import math
from PySide6.QtCore import Qt, QTimer, QPoint, QPointF, QRectF, QUrl
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QFont, QPixmap, QIcon, QDesktopServices, QGuiApplication, QPolygonF
from PySide6.QtWidgets import QWidget, QApplication, QMenu, QSystemTrayIcon, QDialog, QVBoxLayout, QTextEdit, QPlainTextEdit, QDialogButtonBox, QLabel, QPushButton, QMessageBox
import yaml
import qrcode
from .config import ROOT
from .controller import Controller
from .mobile import MobileBridge
from .hotkey import GlobalHotkey
from .art import ACCENTS, draw_pet
from .robot_head import RobotHeadAnimation


class PetWindow(QWidget):
    def __init__(self, cfg: dict, engine: Controller, mobile: MobileBridge | None = None) -> None:
        super().__init__()
        self.cfg, self.engine = cfg, engine
        self.mobile = mobile
        self.mode, self.caption = 'thinking', 'Đang khởi động…'
        self.shape = cfg['pet']['shape']
        self.live_robot = None
        self._creating_live_robot = False
        self.robot_head = RobotHeadAnimation(ROOT / 'assets/robot-heads')
        self.robot_head.set_state(self.mode)
        self.phase = 0
        self.drag_start: QPoint | None = None
        self.dragged = False
        self.closing = False
        self.setWindowTitle('Alex — Ctrl+Space trò chuyện trong Bionic')
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._resize_pet()
        self.setToolTip('Ctrl+Space mở/ẩn và bật/tắt mic. Nói câu hỏi để gửi vào chat Bionic. Bấm pet để ngắt tiếng; kéo để di chuyển.')
        screen = QApplication.primaryScreen().availableGeometry()
        x, y = cfg['pet']['x'], cfg['pet']['y']
        self.move(screen.right() - self.width() - 30 if x is None else x,
                  screen.bottom() - self.height() - 35 if y is None else y)
        self._clamp()
        self.history = QDialog(self)
        self.history.setWindowTitle('Alex — hội thoại trong phiên này')
        self.history.resize(620, 430)
        layout = QVBoxLayout(self.history)
        self.history_text = QTextEdit()
        self.history_text.setReadOnly(True)
        layout.addWidget(self.history_text)
        self.turns: list[tuple[str, str]] = []
        self.current_question = ''
        self.current_answer = ''
        self.last_timing = ''
        self.menu = self._make_menu()
        icon = QPixmap(64, 64)
        icon.fill(Qt.GlobalColor.transparent)
        p = QPainter(icon)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor('#91dbec'))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(5, 9, 54, 46, 16, 16)
        p.setBrush(QColor('#18364b'))
        p.drawEllipse(18, 25, 7, 10)
        p.drawEllipse(39, 25, 7, 10)
        p.end()
        self.setWindowIcon(QIcon(icon))
        self.tray = QSystemTrayIcon(QIcon(icon), self)
        self.tray.setToolTip('Alex · Ctrl+Space mở/ẩn · chat Bionic')
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(lambda reason: self.toggle_visibility() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()
        self.hotkey = GlobalHotkey(self.toggle_visibility)
        logging.info('Ctrl+Space registered=%s', self.hotkey.registered)
        if not self.hotkey.registered:
            self.tray.showMessage('Alex', 'Ctrl+Space đang được ứng dụng khác dùng. Bấm biểu tượng Alex ở khay để mở.')
        else:
            self.tray.showMessage('Alex - Bionic', 'Alex đã mở và sẵn sàng! Bạn có thể nói hoặc bấm Ctrl+Space.', QSystemTrayIcon.MessageIcon.Information, 5000)
        engine.state.connect(self.set_state)
        engine.transcript.connect(self.new_question)
        engine.reply.connect(self.new_answer)
        engine.timing.connect(self.set_timing)
        engine.confirmation.connect(self.confirm_action)
        engine.finished.connect(self._worker_finished)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.setInterval(round(1000 / cfg['pet']['fps']))
        self.robot_release_timer = QTimer(self)
        self.robot_release_timer.setSingleShot(True)
        self.robot_release_timer.setInterval(max(1, int(cfg['pet'].get('renderer_release_seconds', 30))) * 1000)
        self.robot_release_timer.timeout.connect(self._release_hidden_robot)
        self.sprites: dict[str, list[QPixmap]] = {}
        for state in ('idle', 'listening', 'thinking', 'speaking'):
            frames = []
            for path in sorted((ROOT / 'assets/pet' / state).glob('*.png')):
                image = QPixmap(str(path))
                if not image.isNull():
                    frames.append(image.scaled(cfg['pet']['size'] + 32, cfg['pet']['size'] + 32,
                                               Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
            self.sprites[state] = frames
        self._ensure_live_robot()

    def _ensure_live_robot(self) -> None:
        if (self._creating_live_robot or self.live_robot is not None
                or self.shape != 'robot-heads' or not self.isVisible() or self.closing):
            return
        if self.cfg['pet'].get('robot_renderer', 'live') != 'live':
            return
        # WebEngine can re-enter showEvent while making the parent window native.
        self._creating_live_robot = True
        try:
            from .robot_live import LiveRobotHead
            self.live_robot = LiveRobotHead(self, ROOT / 'assets/robot-heads',
                                           self.cfg['pet']['size'],
                                           self.cfg['pet'].get('follow_cursor', True))
            self.live_robot.mode = self.mode
        except Exception:
            logging.exception('Live robot unavailable; using offline sprites')
        finally:
            self._creating_live_robot = False

    def _release_hidden_robot(self) -> None:
        if self.isVisible() and self.shape == 'robot-heads':
            return
        view, self.live_robot = self.live_robot, None
        if view is not None:
            view.shutdown()
            # Destroy the page before its off-the-record profile.
            view.page().destroyed.connect(view.deleteLater)
            view.page().deleteLater()
            logging.info('Robot renderer released while inactive')

    def _make_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction('Mở / ẩn pet · Ctrl+Space', self.toggle_visibility)
        self.pause_action = menu.addAction('Tạm dừng nghe', self.toggle_pause)
        menu.addAction('Xem câu hỏi và câu trả lời', self.history.show)
        menu.addAction('Các cách nói Alex đã học', self.show_learning)
        menu.addAction('Ngắt thao tác / thu hồi kế hoạch', self.engine.interrupt)
        menu.addAction('Công cụ và quyền thao tác: xem trong Bionic', self.open_bionic)
        shapes = menu.addMenu('Hình dáng pet')
        for key, label in [('robot-heads', 'Robot tròn xanh ngọc · robot-heads'),
                           ('mascot', 'Alex hoạt hình (hình cũ)')]:
            action = shapes.addAction(label)
            action.triggered.connect(lambda checked=False, value=key: self.change_shape(value))
        self.follow_action = menu.addAction('Mắt và đầu nhìn theo chuột')
        self.follow_action.setCheckable(True)
        self.follow_action.setChecked(self.cfg['pet'].get('follow_cursor', True))
        self.follow_action.toggled.connect(self.toggle_follow_cursor)
        menu.addSeparator()
        menu.addAction('Mở Bionic', self.open_bionic)
        if self.mobile:
            menu.addAction('Kết nối điện thoại Alex', self.show_phone_pairing)
            menu.addAction('Quên điện thoại đã ghép…', self.revoke_phone)
        menu.addAction('Mở cấu hình', lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(ROOT / 'config.yaml'))))
        menu.addAction('Nhật ký thời gian / lỗi', lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(ROOT / 'logs/pet.log'))))
        menu.addAction('Hướng dẫn', lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(ROOT / 'README.md'))))
        menu.addSeparator()
        menu.addAction('Thoát Alex', self.quit_pet)
        return menu

    def show_phone_pairing(self) -> None:
        if not self.mobile:
            return
        try:
            link = self.mobile.pairing_link()
        except Exception as exc:
            logging.exception('Phone pairing link failed')
            self.engine.state.emit('error', str(exc))
            return
        qr = qrcode.QRCode(border=2, box_size=7)
        qr.add_data(link)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        box = 6
        pix = QPixmap(len(matrix) * box, len(matrix) * box)
        pix.fill(QColor('white'))
        painter = QPainter(pix)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('black'))
        for y, row in enumerate(matrix):
            for x, dark in enumerate(row):
                if dark:
                    painter.drawRect(x * box, y * box, box, box)
        painter.end()
        qr_path = ROOT / 'data/phone-pairing-qr.png'
        if not pix.save(str(qr_path), 'PNG'):
            logging.error('Phone pairing QR could not be saved to %s', qr_path)
        else:
            logging.info('Phone pairing QR ready at %s', qr_path)
        if hasattr(self, 'qr_cleanup_timer'):
            self.qr_cleanup_timer.stop()
        self.qr_cleanup_timer = QTimer(self)
        self.qr_cleanup_timer.setSingleShot(True)
        self.qr_cleanup_timer.timeout.connect(lambda: qr_path.unlink(missing_ok=True))
        self.qr_cleanup_timer.start(300000)
        dialog = QDialog(None)
        dialog.setWindowTitle('Alex — kết nối điện thoại')
        dialog.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Mở ứng dụng Alex trên Android, quét mã bằng Camera của điện thoại.\nPC và điện thoại cần cùng Wi-Fi. Mã dùng một lần, hết hạn sau 5 phút.'))
        image = QLabel(dialog); image.setPixmap(pix)
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(image)
        copy = QPushButton('Sao chép liên kết ghép nối')
        copy.clicked.connect(lambda: QApplication.clipboard().setText(link))
        layout.addWidget(copy)
        watcher = QTimer(dialog)
        watcher.timeout.connect(lambda: dialog.accept() if not self.mobile.pairing_active() else None)
        watcher.start(500)
        dialog.adjustSize()
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            dialog.move(area.center().x() - dialog.width() // 2,
                        area.center().y() - dialog.height() // 2)
        QTimer.singleShot(0, lambda: (dialog.raise_(), dialog.activateWindow()))
        dialog.exec()

    def revoke_phone(self) -> None:
        if not self.mobile:
            return
        choice = QMessageBox.question(None, 'Alex — quên điện thoại',
            'Quên điện thoại đã ghép? Sau đó bạn phải quét mã QR mới để nói chuyện trên điện thoại.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if choice == QMessageBox.StandardButton.Yes:
            self.mobile.revoke()

    def show_learning(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle('Alex — các cách nói đã học')
        dialog.resize(620, 430)
        layout = QVBoxLayout(dialog)
        view = QTextEdit(dialog); view.setReadOnly(True)
        rows = self.engine.learning.rows() if self.engine.learning else []
        lines = ['Dạy bằng câu: Khi tôi nói nhạc làm việc thì mở nhạc.',
                 'Quên bằng câu: Quên cách nói nhạc làm việc.', '']
        for row in rows:
            lines.append(f"{row['phrase']} → {row['target']}\n"
                         f"Đã kiểm tra thành công: {row['successes']} · Chưa xác nhận: {row['failures']}\n")
        if not rows:
            lines.append('Chưa có cách nói đã lưu.')
        view.setPlainText('\n'.join(lines)); layout.addWidget(view)
        dialog.exec()

    def open_bionic(self) -> None:
        # Keep process startup and window discovery off the GUI thread.
        from .launcher import open_bionic
        import threading
        def launch() -> None:
            try:
                open_bionic(self.cfg['bionic']['bridge_port'])
            except Exception as exc:
                self.engine.state.emit('error', str(exc))
        threading.Thread(target=launch, daemon=True).start()

    def toggle_visibility(self) -> None:
        if self.isVisible():
            self.engine.paused.set()
            self.engine.interrupt()
            if self.engine.mic:
                self.engine.mic.gate(False)
            self.hide()
            logging.info('Pet hidden; microphone gated off')
        else:
            self.engine.paused.clear()
            self.show()
            self.raise_()
            logging.info('Pet shown; conversation microphone enabled')

    def toggle_computer(self, enabled: bool) -> None:
        self.engine.computer_enabled = enabled
        if not enabled:
            self.engine.interrupt()

    def confirm_action(self, description: str, decision: object) -> None:
        # The pet can be hidden; a child dialog may then exist without appearing onscreen.
        box = QDialog(None)
        box.setWindowTitle('Alex — cấp phép thao tác')
        box.resize(700, 480)
        box.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint |
                           Qt.WindowType.WindowCloseButtonHint)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            box.move(area.center().x() - box.width() // 2,
                     area.center().y() - box.height() // 2)
        layout = QVBoxLayout(box)
        layout.addWidget(QLabel('Đọc nội dung và chọn Cho phép hoặc Hủy.'))
        details = QPlainTextEdit(box)
        details.setReadOnly(True)
        details.setPlainText(description)
        layout.addWidget(details)
        buttons = QDialogButtonBox(box)
        allow = buttons.addButton('Cho phép', QDialogButtonBox.ButtonRole.AcceptRole)
        cancel = buttons.addButton('Hủy', QDialogButtonBox.ButtonRole.RejectRole)
        allow.clicked.connect(box.accept)
        cancel.clicked.connect(box.reject)
        cancel.setDefault(True)
        layout.addWidget(buttons)
        timer = QTimer(box)
        timer.timeout.connect(lambda: box.reject() if decision.done.is_set() else None)
        timer.start(100)
        QTimer.singleShot(0, lambda: (box.raise_(), box.activateWindow()))
        approved = box.exec() == QDialog.DialogCode.Accepted
        decision.allowed = approved
        decision.done.set()

    def toggle_pause(self) -> None:
        if self.engine.paused.is_set():
            self.engine.paused.clear()
        else:
            self.engine.paused.set()
            self.engine.interrupt()
            if self.engine.mic:
                self.engine.mic.gate(False)

    def change_shape(self, shape: str) -> None:
        self.shape = shape
        self._resize_pet()
        self._clamp()
        self._ensure_live_robot()
        if self.live_robot is not None:
            self.live_robot.sync(self.mode, self.isVisible() and shape == 'robot-heads')
        if shape == 'robot-heads':
            self.robot_release_timer.stop()
        else:
            self.robot_release_timer.start()
        self.save_position()
        self.update()

    def toggle_follow_cursor(self, enabled: bool) -> None:
        self.cfg['pet']['follow_cursor'] = enabled
        if self.live_robot is not None:
            self.live_robot.follow = enabled
            self.live_robot.sync(self.mode, self.isVisible() and self.shape == 'robot-heads')
        self.save_position()

    def _resize_pet(self) -> None:
        # Extra headroom contains the antenna and hops above the round robot.
        size = self.cfg['pet']['size']
        self.resize(max(218, size + 60), size + (151 if self.shape == 'robot-heads' else 112))

    def save_position(self) -> None:
        # Merge just UI settings so edits made while running are retained.
        path = ROOT / 'config.yaml'
        cfg = yaml.safe_load(path.read_text(encoding='utf-8'))
        cfg['pet'].update(x=self.x(), y=self.y(), shape=self.shape,
                          follow_cursor=self.cfg['pet'].get('follow_cursor', True))
        temporary = path.with_suffix('.yaml.tmp')
        temporary.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding='utf-8')
        temporary.replace(path)

    def _clamp(self) -> None:
        point = self.pos() + QPoint(self.width() // 2, self.height() // 2)
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        rect = screen.availableGeometry()
        self.move(max(rect.left(), min(self.x(), rect.right() - self.width() + 1)),
                  max(rect.top(), min(self.y(), rect.bottom() - self.height() + 1)))

    def set_state(self, mode: str, caption: str) -> None:
        self.mode, self.caption = mode, caption
        self.robot_head.set_state(mode)
        if self.live_robot is not None:
            self.live_robot.sync(mode, self.isVisible() and self.shape == 'robot-heads')
        self.pause_action.setText('Bật mic trở lại' if mode == 'paused' else 'Tạm dừng nghe')
        self.update()

    def new_question(self, question: str) -> None:
        if self.current_question:
            self.turns.append((self.current_question, self.current_answer))
            self.turns = self.turns[-20:]
        self.current_question, self.current_answer = question, ''
        self.render_history()

    def new_answer(self, answer: str) -> None:
        self.current_answer = answer
        self.render_history()

    def set_timing(self, timing: str) -> None:
        self.last_timing = timing
        self.render_history()

    def render_history(self) -> None:
        text = '\n\n'.join(f'Bạn: {q}\nAlex: {a}' for q, a in self.turns + [(self.current_question, self.current_answer)])
        self.history_text.setPlainText(text + '\n\n' + self.last_timing)
        bar = self.history_text.verticalScrollBar()
        bar.setValue(bar.maximum())

    def animate(self) -> None:
        if not self.isVisible():
            return
        self.phase += 1
        if self.live_robot is not None:
            self.live_robot.sync(self.mode, self.shape == 'robot-heads')
        self.update()

    def hideEvent(self, event: object) -> None:
        if hasattr(self, 'timer'):
            self.timer.stop()
        self.robot_head.suspend(True)
        if self.live_robot is not None:
            self.live_robot.sync(self.mode, False)
        if hasattr(self, 'robot_release_timer'):
            self.robot_release_timer.start()
        super().hideEvent(event)

    def showEvent(self, event: object) -> None:
        self.robot_head.suspend(False)
        if hasattr(self, 'robot_release_timer'):
            self.robot_release_timer.stop()
        self._ensure_live_robot()
        if self.live_robot is not None:
            self.live_robot.sync(self.mode, self.shape == 'robot-heads')
        if hasattr(self, 'timer'):
            self.timer.start(round(1000 / self.cfg['pet']['fps']))
        super().showEvent(event)

    def paintEvent(self, event: object) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setPen(Qt.PenStyle.NoPen)
        bubble = QRectF(8, 5, self.width() - 16, 69)
        p.setBrush(QColor(12, 31, 47, 65))
        p.drawRoundedRect(bubble.translated(0, 3), 19, 19)
        gradient = QLinearGradient(bubble.topLeft(), bubble.bottomRight())
        gradient.setColorAt(0, QColor('#254b60'))
        gradient.setColorAt(1, QColor('#172f45'))
        p.setBrush(gradient)
        p.setPen(QPen(QColor('#4c7483'), 1))
        p.drawRoundedRect(bubble, 19, 19)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#172f45'))
        p.drawPolygon(QPolygonF([QPointF(self.width()/2-7, 72),
                                 QPointF(self.width()/2+7, 72),
                                 QPointF(self.width()/2, 82)]))
        accent = QColor(ACCENTS.get(self.mode, ACCENTS['idle']))
        p.setBrush(accent)
        p.drawEllipse(QRectF(self.width() - 28, 15, 7, 7))
        p.setPen(QColor('#f6fbff'))
        p.setFont(QFont('Segoe UI', 9, QFont.Weight.Medium))
        p.drawText(QRectF(19, 11, self.width() - 45, 57),
                   Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.caption)
        s = self.cfg['pet']['size']
        x, y = (self.width() - s) / 2, 84
        sprite_state = self.mode if self.mode in ('idle', 'listening', 'thinking', 'speaking') else 'idle'
        sprites = self.sprites.get(sprite_state, []) if self.shape == 'mascot' else []
        live_ready = (self.live_robot is not None and self.live_robot.ready
                      and not self.live_robot.failed)
        robot_drawn = self.shape == 'robot-heads' and (live_ready or self.robot_head.paint(
            p, QRectF(x, 116, s, s)))
        if robot_drawn:
            pass
        elif sprites:
            pixmap = sprites[(self.phase // 3) % len(sprites)]
            bounce = math.sin(self.phase / 13) * (2.8 if self.mode == 'idle' else 1.8)
            pulse = 1 + (0.025 * math.sin(self.phase / 4) if self.mode == 'speaking' else 0)
            width = (s + 28) * pulse
            p.setOpacity(.63 if self.mode == 'paused' else 1)
            p.drawPixmap(QRectF((self.width() - width)/2, 79 + bounce, width, s + 28),
                         pixmap, QRectF(pixmap.rect()))
            p.setOpacity(1)
        else:
            p.save()
            p.translate(x, y)
            p.scale(s / 170, s / 170)
            draw_pet(p, 'robot' if self.shape == 'robot-heads' else self.shape, self.mode, self.phase)
            p.restore()
        if not sprites:
            name_width = 66
            name_rect = QRectF((self.width() - name_width)/2, self.height() - 26, name_width, 23)
            p.setPen(QPen(QColor('#537687'), 1))
            p.setBrush(QColor('#19364c'))
            p.drawRoundedRect(name_rect, 11, 11)
            p.setPen(QColor('#f4fbff'))
            p.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
            p.drawText(name_rect, Qt.AlignmentFlag.AlignCenter, self.cfg['name'])

    def mousePressEvent(self, event: object) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start = event.globalPosition().toPoint() - self.pos()
            self.press_position = event.globalPosition().toPoint()
            self.dragged = False

    def mouseMoveEvent(self, event: object) -> None:
        if self.drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if (event.globalPosition().toPoint() - self.press_position).manhattanLength() > 5:
                self.dragged = True
            if self.dragged:
                self.move(event.globalPosition().toPoint() - self.drag_start)

    def mouseReleaseEvent(self, event: object) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.drag_start is not None:
            self.drag_start = None
            if self.dragged:
                self._clamp()
                self.save_position()
            else:
                self.engine.toggle()

    def contextMenuEvent(self, event: object) -> None:
        self.menu.exec(event.globalPos())

    def quit_pet(self) -> None:
        self.closing = True
        self.set_state('paused', 'Đang đóng…')
        self.save_position()
        self.engine.stop()
        self.hotkey.close()
        self.timer.stop()
        self.robot_release_timer.stop()
        self.robot_head.close()
        if self.live_robot is not None:
            self.live_robot.shutdown()
        if not self.engine.isRunning():
            QApplication.quit()

    def _worker_finished(self) -> None:
        if self.closing:
            QApplication.quit()

    def closeEvent(self, event: object) -> None:
        event.ignore()
        self.quit_pet()
