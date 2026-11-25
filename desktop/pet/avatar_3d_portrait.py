"""Local 3-D avatar in the command center; audio level never leaves this process."""
from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from .config import ROOT
from .human_portrait import HologramFace as PreviousFace
from . import voice_motion


class HologramFace(PreviousFace):
    """Keep the established widget API while displaying a real glTF model."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._web = None
        self._profile = self._interceptor = self._page = None
        self._creating = False
        self._last_push = 0.
        self.timer.setInterval(50)
        self.setAccessibleName('Nhân vật trợ lý Alex 3D')
        self.setWhatsThis('Mô hình 3D được tải từ laptop. Mắt chớp và hàm theo gần đúng âm lượng giọng phát; không đồng bộ từng âm tiết.')

    def _ensure_view(self):
        if self._web is not None or self._creating:
            return
        # Qt's offscreen platform cannot reliably create Chromium's GPU context;
        # keep the prior Qt renderer for noninteractive unit tests.
        if QApplication.platformName() == 'offscreen':
            return
        self._creating = True
        try:
            from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile,
                QWebEngineSettings, QWebEngineUrlRequestInterceptor)
            from PySide6.QtWebEngineWidgets import QWebEngineView
            root = (ROOT/'assets'/'avatar3d').resolve()
            index = (root/'index.html').resolve()

            class LocalOnly(QWebEngineUrlRequestInterceptor):
                def interceptRequest(self, info):
                    url = info.requestUrl()
                    if url.scheme() in ('blob', 'data'):
                        return
                    if url.isLocalFile():
                        try:
                            Path(url.toLocalFile()).resolve().relative_to(root)
                            return
                        except (ValueError, OSError):
                            pass
                    info.block(True)

            owner = self

            class LocalPage(QWebEnginePage):
                def acceptNavigationRequest(self, url, kind, is_main):
                    if url.toString() == 'about:blank':
                        return True
                    if not url.isLocalFile():
                        return False
                    try:
                        return Path(url.toLocalFile()).resolve() == index
                    except OSError:
                        return False

                def javaScriptConsoleMessage(self, level, message, line, source):
                    if message == 'ALEX_EXIT_FULLSCREEN':
                        win = owner.window()
                        if hasattr(win, '_escape'):
                            win._escape()

            self._profile = QWebEngineProfile(self)  # off-the-record profile
            self._interceptor = LocalOnly(self._profile)
            self._profile.setUrlRequestInterceptor(self._interceptor)
            self._web = QWebEngineView(self)
            self._page = LocalPage(self._profile, self._web)
            self._web.setPage(self._page)
            settings = self._page.settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
            settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
            self._web.setGeometry(self.rect())
            self._web.loadFinished.connect(self._loaded)
            self._web.load(QUrl.fromLocalFile(str(index)))
            self._web.setVisible(self.active)
        except Exception:
            logging.exception('Could not initialize local 3D avatar')
            from PySide6.QtWidgets import QLabel
            self._web = QLabel('Không mở được nhân vật 3D trên máy này.', self)
            self._web.setStyleSheet('background: #153b39; color: white; padding: 24px;')
            self._web.setGeometry(self.rect())
            self._web.setWordWrap(True)
            self._web.show()
        finally:
            self._creating = False

    def _loaded(self, ok):
        if not ok:
            logging.warning('Local 3D avatar page failed to load')
        self._push_state()

    def _push_state(self):
        if self._page is None:
            return
        level = voice_motion.level() if self.mode == 'speaking' else 0.
        if not math.isfinite(level):
            level = 0.
        args = ','.join((json.dumps(str(self.mode)), str(max(0., min(1., level))),
                         'true' if self.reduced else 'false', 'true' if self.active else 'false'))
        self._page.runJavaScript(f'if(window.alexState) window.alexState({args});')

    def _tick(self):
        if self._page is None:
            super()._tick()
            return
        self._last_tick = time.monotonic()
        self._push_state()

    def set_active(self, active):
        super().set_active(active)
        if active:
            self._ensure_view()
        if self._web is not None:
            self._web.setVisible(bool(active))
        self._push_state()

    def set_mode(self, mode):
        super().set_mode(mode)
        self._push_state()

    def set_reduced_motion(self, reduced):
        super().set_reduced_motion(reduced)
        self._push_state()

    def resizeEvent(self, event):
        if self._web is not None:
            self._web.setGeometry(self.rect())
        super().resizeEvent(event)
