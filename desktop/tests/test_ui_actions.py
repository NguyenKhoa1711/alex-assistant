"""Decision tests for contact matching; UIA calls are exercised separately on Windows."""
import importlib
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from pet.app_actions import Action

with patch.dict(sys.modules, {'uiautomation': MagicMock()}):
    worker = importlib.import_module('app_action_worker')


class ZaloNode:
    def __init__(self, name='', aid='', children=(), kind='GroupControl', offscreen=False):
        self.Name = name
        self.AutomationId = aid
        self.children = list(children)
        self.ControlTypeName = kind
        self.IsOffscreen = offscreen
        self.IsEnabled = True
    def GetChildren(self):
        return self.children
    def Exists(self, *args):
        return True


def zalo_text(value):
    return ZaloNode(name=value, kind='TextControl')


def zalo_row(aid, parts, metadata=()):
    # Captured structural layout from Zalo 26.10: avatar, title, badges,
    # category/member matches. No real contact identifiers are kept here.
    return ZaloNode(aid=aid, children=[
        ZaloNode(children=[ZaloNode()]),
        ZaloNode(children=[zalo_text(part) for part in parts]),
        ZaloNode(), ZaloNode(children=[zalo_text(part) for part in metadata]),
        ZaloNode(),
    ])


class ContactSelectionTests(unittest.TestCase):
    def test_native_lookup_is_scoped_to_the_zalo_root_and_automation_id(self):
        client = MagicMock()
        root = MagicMock()
        internals = SimpleNamespace(_AutomationClient=SimpleNamespace(
            instance=lambda: SimpleNamespace(IUIAutomation=client)))
        with patch.dict(sys.modules, {'uiautomation.uiautomation': internals}):
            result = worker.zalo_find(root, 'header')
        client.CreatePropertyCondition.assert_called_once_with(worker.auto.PropertyId.AutomationIdProperty, 'header')
        root.Element.FindFirst.assert_called_once_with(4, client.CreatePropertyCondition.return_value)
        self.assertIsNotNone(result)
        root.GroupControl.assert_not_called()

    def test_no_native_match_does_not_pick_another_control(self):
        client = MagicMock()
        root = MagicMock()
        root.Element.FindFirst.return_value = None
        internals = SimpleNamespace(_AutomationClient=SimpleNamespace(
            instance=lambda: SimpleNamespace(IUIAutomation=client)))
        with patch.dict(sys.modules, {'uiautomation.uiautomation': internals}):
            self.assertIsNone(worker.zalo_find(root, 'header'))
        root.GroupControl.assert_not_called()

    def test_header_category_or_message_cannot_verify_wrong_chat(self):
        header = ZaloNode(children=[zalo_text('\uec05'), zalo_text('Người khác'),
            zalo_text('Gia đình'), ZaloNode(aid='chatView', children=[zalo_text('Nguyễn An')])])
        with patch.object(worker, 'zalo_find', return_value=header):
            self.assertFalse(worker.zalo_header_matches(object(), 'Gia đình'))
            self.assertFalse(worker.zalo_header_matches(object(), 'Nguyễn An'))
            self.assertTrue(worker.zalo_header_matches(object(), 'Người khác'))

    def run_search(self, names, query='Nguyễn An', header='Nguyễn An',
                   metadata=(), rows=None, search_value=None, invoke_error=None):
        ui = MagicMock()
        ui.root.EditControl.return_value.Exists.return_value = True
        ui.root.EditControl.return_value.GetValuePattern.return_value.Value = query if search_value is None else search_value
        rows = rows if rows is not None else [zalo_row(f'friend-item-{i}', name, metadata) for i, name in enumerate(names)]
        area = ZaloNode(aid='searchResultList', children=rows)
        heading = ZaloNode(aid='header', children=[zalo_text(header)])
        ui.root.GroupControl.side_effect = lambda **kw: area if kw['AutomationId'] == 'searchResultList' else heading
        def find(_root, aid, kind='GroupControl'):
            if aid == 'contact-search-input':
                return ui.root.EditControl.return_value
            return area if aid == 'searchResultList' else heading
        if invoke_error:
            ui.invoke.side_effect = invoke_error
        with patch.object(worker, 'Ui', return_value=ui), patch.object(worker, 'zalo_find', side_effect=find), patch.object(worker.time, 'sleep'):
            result = worker.zalo(Action('Zalo', 'chat', query))
        return result, ui

    def test_name_split_into_highlighted_parts(self):
        result, ui = self.run_search([['Nguyễn', '\u00a0', 'An']])
        self.assertTrue(result['verified'])
        ui.invoke.assert_called_once()

    def test_category_and_status_are_not_part_of_contact_name(self):
        result, ui = self.run_search([['Đại', '\u00a0', 'ca']], query='Đại ca',
                                   header='Đại ca', metadata=['\uec05', 'Gia đình'])
        self.assertTrue(result['verified'])
        ui.invoke.assert_called_once()

    def test_matched_member_name_does_not_select_an_unrelated_group(self):
        rows = [zalo_row('group-item-1', ['Học tập'], ['Thành viên:', 'Nguyễn An'])]
        result, ui = self.run_search([], rows=rows)
        self.assertFalse(result['verified'])
        ui.invoke.assert_not_called()

    def test_exact_contact_wins_over_groups_containing_that_member(self):
        row = zalo_row('friend-item-1', ['Nguyễn An'], ['Gia đình'])
        rows = [row, zalo_row('group-item-2', ['Học tập'], ['Thành viên:', 'Nguyễn An'])]
        result, ui = self.run_search([], rows=rows)
        self.assertTrue(result['verified'])
        ui.invoke.assert_called_once_with(row)

    def test_message_hit_with_exact_name_is_not_a_contact(self):
        result, ui = self.run_search([], rows=[zalo_row('message-1', ['Nguyễn An'])])
        self.assertFalse(result['verified'])
        ui.invoke.assert_not_called()

    def test_duplicate_exact_names_are_not_opened(self):
        result, ui = self.run_search([['Nguyễn An'], ['Nguyễn An']])
        self.assertFalse(result['verified'])
        self.assertIn('trùng tên', result['message'])
        ui.invoke.assert_not_called()

    def test_partial_name_does_not_open_wrong_person(self):
        result, ui = self.run_search([['Nguyễn Anh'], ['Nguyễn An Bình']])
        self.assertFalse(result['verified'])
        ui.invoke.assert_not_called()

    def test_changed_chat_header_does_not_claim_success(self):
        result, ui = self.run_search([['Nguyễn An']], header='Người khác')
        self.assertFalse(result['verified'])
        ui.invoke.assert_called_once()

    def test_search_edited_by_user_cancels_stale_selection(self):
        result, ui = self.run_search([['Nguyễn An']], search_value='Người khác')
        self.assertFalse(result['verified'])
        ui.invoke.assert_not_called()

    def test_offscreen_result_is_not_selected(self):
        row = zalo_row('friend-item-1', ['Nguyễn An']); row.IsOffscreen = True
        result, ui = self.run_search([], rows=[row])
        self.assertFalse(result['verified'])
        ui.invoke.assert_not_called()

    def test_com_error_after_open_is_verified_without_double_click(self):
        result, ui = self.run_search([['Nguyễn An']],
            invoke_error=worker.COMError(-2147467259, 'stale event', None))
        self.assertTrue(result['verified'])
        ui.invoke.assert_called_once()

    def test_truncated_scan_cannot_claim_a_unique_contact(self):
        area = ZaloNode(children=[zalo_row('friend-item-1', ['Nguyễn An'])])
        with patch.object(worker.time, 'monotonic', side_effect=[0, 6]):
            self.assertIsNone(worker.zalo_matches(area, 'Nguyễn An'))

    def test_unstable_results_are_not_opened(self):
        row = zalo_row('friend-item-1', ['Nguyễn An'])
        with patch.object(worker, 'zalo_matches', side_effect=[[(row, 'Nguyễn An')], None] * 8):
            result, ui = self.run_search([])
        self.assertFalse(result['verified'])
        ui.invoke.assert_not_called()

    def test_message_section_is_not_read_after_contact_results(self):
        message = ZaloNode()
        message.GetChildren = MagicMock(side_effect=AssertionError('Do not read message results'))
        row = zalo_row('friend-item-1', ['Nguyễn An'])
        area = ZaloNode(children=[row, zalo_text('Tin nhắn (2+)'), message])
        self.assertEqual(worker.zalo_matches(area, 'Nguyễn An'), [(row, 'Nguyễn An')])
        message.GetChildren.assert_not_called()


class PlaybackVerificationTests(unittest.TestCase):
    def test_old_track_with_same_title_but_other_artist_is_not_success(self):
        self.assertFalse(worker.song_is_playing('Thiên Lý Ơi của Người khác', 'Thiên Lý Ơi', 'Jack - J97', 'playing'))
        self.assertFalse(worker.song_is_playing('Thiên Lý Ơi', 'Thiên Lý Ơi', 'Jack - J97', 'playing'))
        self.assertTrue(worker.song_is_playing('Thiên Lý Ơi của Jack - J97', 'Thiên Lý Ơi', 'Jack - J97', 'playing'))

    def test_event_error_after_invoke_checks_state_without_second_click(self):
        ui = MagicMock()
        ui.invoke.side_effect = worker.COMError(-2147467259, 'stale event', None)
        verify = MagicMock(side_effect=[worker.COMError(-2147467259, 'stale read', None),
                                       {'verified': True, 'message': 'paused'}])
        with patch.object(worker.time, 'sleep'):
            result = worker.invoke_and_verify(ui, object(), verify)
        self.assertTrue(result['verified'])
        ui.invoke.assert_called_once()

    def test_no_success_without_confirmed_state(self):
        ui = MagicMock()
        with patch.object(worker.time, 'sleep'):
            result = worker.invoke_and_verify(ui, object(), lambda: None, attempts=3)
        self.assertIsNone(result)
        ui.invoke.assert_called_once()

    def test_read_retries_stale_element(self):
        read = MagicMock(side_effect=[worker.COMError(-2147467259, 'stale', None), 'playing'])
        with patch.object(worker.time, 'sleep'):
            self.assertEqual(worker.retry_uia_read(read)(), 'playing')

    def test_spotify_auto_selects_first_best_match_when_duplicates_exist(self):
        b1 = SimpleNamespace(ControlTypeName='ButtonControl', IsOffscreen=False, Name='Phát Lạc Trôi của Sơn Tùng M-TP')
        b2 = SimpleNamespace(ControlTypeName='ButtonControl', IsOffscreen=False, Name='Phát Lạc Trôi của Ca Sĩ Khác')
        chosen = worker.select_spotify_match([b1, b2], 'Lạc Trôi')
        self.assertIsNotNone(chosen)
        self.assertIs(chosen[0], b1)
        self.assertEqual((chosen[1], chosen[2]), ('Lạc Trôi', 'Sơn Tùng M-TP'))

    def test_spotify_selects_by_artist_or_genre_query(self):
        b1 = SimpleNamespace(ControlTypeName='ButtonControl', IsOffscreen=False, Name='Phát Cơn Mưa Ngang Qua của Sơn Tùng M-TP')
        chosen = worker.select_spotify_match([b1], 'Sơn Tùng M-TP')
        self.assertIsNotNone(chosen)
        self.assertIs(chosen[0], b1)
        b2 = SimpleNamespace(ControlTypeName='ButtonControl', IsOffscreen=False, Name='Phát Chúng Ta Của Hiện Tại của Sơn Tùng M-TP')
        chosen_cua = worker.select_spotify_match([b2], 'Chúng Ta', 'Hiện Tại')
        self.assertIsNotNone(chosen_cua)
        self.assertEqual((chosen_cua[1], chosen_cua[2]), ('Chúng Ta Của Hiện Tại', 'Sơn Tùng M-TP'))

    def test_pause_falls_back_to_youtube_when_spotify_not_open(self):
        with patch.object(worker, 'is_spotify_open', return_value=False), \
             patch.object(worker, 'browser_youtube_action', return_value={'message': 'Mình đã tạm dừng nhạc đang phát trên YouTube.', 'verified': True}) as yt:
            res = worker.spotify(Action('Spotify', 'pause'))
        self.assertTrue(res['verified'])
        self.assertIn('YouTube', res['message'])
        yt.assert_called_once_with('pause')

    def test_youtube_song_opens_direct_video_when_resolved(self):
        with patch.object(worker, 'find_youtube_video', return_value=('dQw4w9WgXcQ', 'Lạc Trôi Official')), \
             patch.object(worker, 'open_web', return_value=SimpleNamespace(verified=True)) as web, \
             patch.object(worker, 'is_youtube_open', return_value=False), \
             patch.object(worker, 'app_windows', return_value=[101]), \
             patch.object(worker, '_window_title', return_value='Lạc Trôi - YouTube'), \
             patch.object(worker, 'browser_youtube_action', return_value={'verified': True, 'message': 'ok'}), \
             patch.object(worker.time, 'sleep'):
            res = worker.youtube(Action('YouTube', 'song', 'Lạc Trôi'))
        self.assertTrue(res['verified'])
        self.assertIn('Lạc Trôi Official', res['message'])
        web.assert_called_once_with('https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'YouTube')

    def test_youtube_search_remains_available_when_video_lookup_fails(self):
        with patch.object(worker, 'find_youtube_video', return_value=None), \
             patch.object(worker, 'open_web', return_value=SimpleNamespace(verified=True)) as web, \
             patch.object(worker, 'click_first_youtube_result', return_value={'verified': True, 'message': 'opened'}) as pick:
            res = worker.youtube(Action('YouTube', 'song', 'Lạc Trôi', 'Sơn Tùng'))
        self.assertTrue(res['verified'])
        from urllib.parse import parse_qs, urlparse
        self.assertEqual(parse_qs(urlparse(web.call_args.args[0]).query)['search_query'], ['Lạc Trôi Sơn Tùng'])
        pick.assert_called_once_with('Lạc Trôi Sơn Tùng')

    def test_failed_browser_open_does_not_claim_song_is_playing(self):
        with patch.object(worker, 'find_youtube_video', return_value=('dQw4w9WgXcQ', 'Lạc Trôi')), \
             patch.object(worker, 'is_youtube_open', return_value=False), \
             patch.object(worker, 'open_web', return_value=SimpleNamespace(verified=False)), \
             patch.object(worker, 'close_previous_youtube_tabs') as close:
            res = worker.youtube(Action('YouTube', 'song', 'Lạc Trôi'))
        self.assertFalse(res['verified'])
        close.assert_not_called()


if __name__ == '__main__':
    unittest.main()
