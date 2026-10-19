"""Original robot-heads geometry/springs, isolated offline in Qt's canvas view."""
from __future__ import annotations
import json
import logging
import math
import time
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import QWidget
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile,
                                    QWebEngineSettings, QWebEngineUrlRequestInterceptor)
from PySide6.QtWebEngineWidgets import QWebEngineView


def local_document_allowed(url: QUrl) -> bool:
    return url.toString() == 'about:blank' or (
        url.scheme() == 'data' and url.toString().startswith('data:text/html'))


class OfflineOnly(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info: object) -> None:
        # The document is in memory with inline code. No file/network subresources.
        info.block(not local_document_allowed(info.requestUrl()))


class LocalPage(QWebEnginePage):
    def acceptNavigationRequest(self, url: QUrl, kind: object, main_frame: bool) -> bool:
        return main_frame and local_document_allowed(url)

    def javaScriptConsoleMessage(self, level: object, message: str, line: int, source: str) -> None:
        if level == self.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            logging.warning('Robot canvas JS line %s: %s', line, message[:200])


class LiveRobotHead(QWebEngineView):
    def __init__(self, parent: QWidget, assets: Path, size: int, follow: bool = True) -> None:
        super().__init__(parent)
        self.ready = False
        self.closed = False
        self.failed = False
        self.pending = False
        self.follow = follow
        self.mode = 'idle'
        self.size = size
        self.last_draw = 0.0
        self.last_motion = 0.0
        self.last_pointer = None
        self.last_sent = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setStyleSheet('background: transparent; border: 0;')
        self.profile = QWebEngineProfile(self)
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self.interceptor = OfflineOnly(self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.profile.downloadRequested.connect(lambda item: item.cancel())
        page = LocalPage(self.profile, self)
        page.setBackgroundColor(QColor(Qt.GlobalColor.transparent))
        page.setAudioMuted(True)
        page.permissionRequested.connect(lambda permission: permission.deny())
        page.fileSystemAccessRequested.connect(lambda request: request.reject())
        settings = page.settings()
        attrs = QWebEngineSettings.WebAttribute
        for attr in (attrs.LocalContentCanAccessRemoteUrls, attrs.LocalContentCanAccessFileUrls,
                     attrs.JavascriptCanOpenWindows, attrs.JavascriptCanAccessClipboard,
                     attrs.LocalStorageEnabled, attrs.PluginsEnabled, attrs.WebGLEnabled,
                     attrs.HyperlinkAuditingEnabled, attrs.FullScreenSupportEnabled):
            settings.setAttribute(attr, False)
        self.setPage(page)
        self.hide()
        self.loadFinished.connect(self._loaded)
        page.renderProcessTerminated.connect(self._crashed)
        self._place()
        html = (assets / 'live.html').read_text(encoding='utf-8')
        self.setHtml(html, QUrl('about:blank'))

    def _place(self) -> None:
        # Same frameFor(circle, antenna, size) geometry as the vendored renderer.
        # Base frame scales smoothly; a few spare pixels contain round-off at DPI changes.
        scale = self.size / 128
        pad_top, pad_bottom, pad_side = math.ceil(40*scale), math.ceil(16*scale), math.ceil(scale)
        self.setGeometry(round((self.parentWidget().width()-self.size)/2)-pad_side,
                         116-pad_top, self.size+2*pad_side, self.size+pad_top+pad_bottom+2)

    def _loaded(self, success: bool) -> None:
        if self.closed:
            return
        if not success:
            self._crashed('load', 0)
            return
        self.page().runJavaScript('Boolean(window.alexRobot)', self._ready)

    def _ready(self, success: bool) -> None:
        if self.closed:
            return
        if not success:
            self._crashed('script', 0)
            return
        self.ready = True
        logging.info('Robot-heads live ready: cursor tracking; offline canvas')
        self.parentWidget().update()
        parent = self.parentWidget()
        self.sync(self.mode, parent.isVisible() and parent.shape == 'robot-heads')

    def _crashed(self, status: object, code: int) -> None:
        if self.closed:
            return
        self.failed, self.ready, self.pending = True, False, False
        self.hide()
        logging.warning('Robot live renderer stopped (%s/%s); sprite fallback active', status, code)
        self.parentWidget().update()

    def _sent(self, result: object) -> None:
        self.pending = False

    def sync(self, mode: str, visible: bool) -> None:
        self.mode = mode
        if self.closed or not self.ready or self.failed:
            return
        if self.isVisible() != visible:
            self.setVisible(visible)
            self.page().setVisible(visible)
        if self.pending and visible:
            return
        point = self.mapFromGlobal(QCursor.pos())
        now = time.monotonic()
        if self.follow and point != self.last_pointer:
            self.last_motion = now
        self.last_pointer = point
        flags = (mode, visible, self.follow)
        if flags == self.last_sent:
            if not visible:
                return
            interval = 0 if mode not in ('idle', 'paused') or now-self.last_motion < 1.2 else 1/8
            if now-self.last_draw < interval:
                return
        self._place()
        self.last_draw, self.last_sent = now, flags
        payload = {'state':mode, 'visible':visible, 'follow':self.follow, 'size':self.size,
                   'pointer':{'x':point.x(), 'y':point.y()} if visible else None}
        self.pending = True
        self.page().runJavaScript('window.alexRobot && window.alexRobot.tick('+json.dumps(payload)+')', self._sent)

    def shutdown(self) -> None:
        if self.ready:
            self.sync(self.mode, False)
        self.closed = True
        self.ready = False
        self.hide()
