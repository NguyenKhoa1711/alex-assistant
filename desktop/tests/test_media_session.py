import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from pet.app_actions import Action, parse_action
from pet.media_session import _choose, _control

class Session:
    def __init__(self, name, state):
        self.source_app_user_model_id = name
        self.state = state
        self.calls = 0
    def get_playback_info(self):
        return SimpleNamespace(playback_status=SimpleNamespace(name=self.state))
    async def try_pause_async(self):
        self.calls += 1; self.state = 'PAUSED'; return True
    async def try_play_async(self):
        self.calls += 1; self.state = 'PLAYING'; return True

class MediaTests(unittest.TestCase):
    def test_generic_vs_explicit_intent(self):
        self.assertTrue(parse_action('Dừng phát nhạc').auto_media)
        self.assertTrue(parse_action('Phát nhạc').auto_media)
        self.assertFalse(parse_action('Dừng nhạc trên Spotify').auto_media)
        self.assertFalse(parse_action('Dừng nhạc trên YouTube').auto_media)
    def test_select_playing_media_instead_of_open_but_paused_spotify(self):
        spotify, chrome = Session('Spotify', 'PAUSED'), Session('Chrome', 'PLAYING')
        self.assertIs(_choose([spotify, chrome], spotify, Action('Spotify', 'pause', auto_media=True)), chrome)
        self.assertIs(_choose([spotify, chrome], chrome, Action('Spotify', 'pause')), spotify)
        self.assertIsNone(_choose([chrome,Session('Edge','PLAYING')], None, Action('Spotify','pause',auto_media=True)))
    def test_changes_session_once_and_verifies(self):
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
        # WinRT static classes cannot be monkeypatched; inject a fake import module.
        import sys, types
        session=Session('Chrome', 'PLAYING')
        manager=SimpleNamespace(get_sessions=lambda:[session],get_current_session=lambda:session)
        fake=types.ModuleType('winrt.windows.media.control')
        fake.GlobalSystemMediaTransportControlsSessionManager=SimpleNamespace(request_async=AsyncMock(return_value=manager))
        with patch.dict(sys.modules, {'winrt.windows.media.control':fake}):
            result=asyncio.run(_control(Action('Spotify','pause',auto_media=True),lambda:True))
            self.assertTrue(result['verified']); self.assertEqual(session.calls,1)
            result=asyncio.run(_control(Action('Spotify','pause',auto_media=True),lambda:True))
            self.assertTrue(result['verified']); self.assertEqual(session.calls,1)
            result=asyncio.run(_control(Action('Spotify','play',auto_media=True),lambda:True))
            self.assertTrue(result['verified']); self.assertEqual(session.calls,2)

if __name__ == '__main__': unittest.main()
