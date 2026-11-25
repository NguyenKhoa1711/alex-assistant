"""Control one verified Windows media session without toggling blindly."""
from __future__ import annotations
import asyncio
import time


def _status(session):
    try:
        return session.get_playback_info().playback_status.name.upper()
    except Exception:
        return 'UNKNOWN'


def _matches(session, app):
    source = str(session.source_app_user_model_id).casefold()
    if app == 'Spotify':
        return 'spotify' in source
    return any(name in source for name in ('chrome', 'msedge', 'firefox', 'brave', 'opera', 'coccoc'))


def _choose(sessions, current, action):
    if not action.auto_media:
        matches = [s for s in sessions if _matches(s, action.app)]
        if current in matches:
            return current
        return matches[0] if len(matches) == 1 else None
    playing = [s for s in sessions if _status(s) == 'PLAYING']
    if action.operation == 'pause':
        if current in playing:
            return current
        if len(playing) == 1:
            return playing[0]
        if not playing and current in sessions and _status(current) in ('PAUSED', 'STOPPED'):
            return current
        if not playing and len(sessions) == 1 and _status(sessions[0]) in ('PAUSED', 'STOPPED'):
            return sessions[0]
        return None
    # Windows designates its best candidate for media-key resume.
    if current in sessions:
        return current
    paused = [s for s in sessions if _status(s) in ('PAUSED', 'STOPPED')]
    return paused[0] if len(paused) == 1 else None


async def _control(action, youtube_open):
    try:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
    except ImportError:
        return None  # Existing bounded UIA path stays available.
    sent = False
    try:
        manager = await asyncio.wait_for(Manager.request_async(), timeout=3)
        sessions = list(manager.get_sessions())
        current = manager.get_current_session()
        if not action.auto_media and action.app == 'YouTube' and not youtube_open():
            return None
        session = _choose(sessions, current, action)
        if session is None:
            if action.auto_media and len(sessions) > 1:
                return {'message': 'Mình chưa rõ trình phát nào cần điều khiển. Bạn nói tên ứng dụng giúp mình nhé.', 'verified': False}
            return None
        before = _status(session)
        wanted = 'PLAYING' if action.operation == 'play' else 'PAUSED'
        if before == wanted or (action.operation == 'pause' and before == 'STOPPED'):
            return {'message': 'Nhạc đang phát rồi.' if wanted == 'PLAYING' else 'Nhạc đã tạm dừng rồi.', 'verified': True}
        if before not in ('PLAYING', 'PAUSED', 'STOPPED'):
            return {'message': 'Mình chưa xác định được trạng thái trình phát. Bạn kiểm tra lại nhé.', 'verified': False}
        # Once dispatched, do not retry or fall back: the first request may have landed.
        try:
            sent = True
            attempted = await asyncio.wait_for(session.try_play_async() if action.operation == 'play'
                                                else session.try_pause_async(), timeout=3)
        except Exception:
            return {'message': 'Mình chưa xác nhận được trình phát đã thay đổi; bạn kiểm tra trước khi thử lại nhé.', 'verified': False}
        if not attempted:
            return {'message': 'Trình phát chưa nhận lệnh. Bạn kiểm tra ứng dụng đang phát nhạc nhé.', 'verified': False}
        for _ in range(12):
            if _status(session) == wanted:
                return {'message': 'Mình đã phát tiếp nhạc.' if wanted == 'PLAYING' else 'Mình đã tạm dừng nhạc.', 'verified': True}
            await asyncio.sleep(.15)
        return {'message': 'Đã gửi lệnh nhưng trình phát chưa xác nhận; bạn kiểm tra trước khi thử lại nhé.', 'verified': False}
    except Exception:
        if sent:
            return {'message': 'Mình chưa xác nhận được trình phát; bạn kiểm tra trước khi thử lại nhé.', 'verified': False}
        return None


def control_media(action, youtube_open=lambda: False):
    if action.operation not in ('play', 'pause'):
        return None
    try:
        return asyncio.run(_control(action, youtube_open))
    except (OSError, RuntimeError):
        return None
