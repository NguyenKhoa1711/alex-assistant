from __future__ import annotations
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, MagicMock
import numpy as np
from pet.apps import (requested_app, requested_shortcut, requested_system_app,
                      requested_app_path, open_registered_app, LaunchResult,
                      requested_web, open_web, matches_app_window,
                      suggest_installed_app, AppSuggestion, launch_name)
from pet.config import load_config
from pet.controller import Controller
from pet.minecraft import launch_minecraft, wants_minecraft_game
from pet.audio import Utterance
from pet.bionic import finished_answer


class AppCommandTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()
        self.entries = self.cfg['apps']['entries']

    def test_explicit_app_aliases(self):
        for question, expected in [('Mở Spotify giúp mình.', 'Spotify'),
                                   ('Mở suppotify', 'Spotify'),
                                   ('Hãy mở cho tôi Antigravity.', 'Antigravity'),
                                   ('Hãy mở cho tôi ra lô.', 'Zalo'),
                                   ('Bật Google Chrome lên', 'Chrome'),
                                   ('Hãy mở máy tính bỏ túi', 'Calculator')]:
            with self.subTest(question=question):
                self.assertEqual(requested_app(question, self.entries)['name'], expected)

    def test_never_treats_negation_explanation_or_multi_action_as_launch(self):
        for text in ['Đừng mở Spotify', 'Cách mở Spotify', 'Mở Spotify rồi xóa tệp',
                     'Mở Spotify.exe --flag', 'Mở Spot', 'Mở powershell', 'Không bật Chrome',
                     'Đừng mở ra lô', 'Tôi nói ra lô chứ không phải tên khác']:
            with self.subTest(text=text):
                self.assertIsNone(requested_app(text, self.entries))

    def test_natural_open_intent_keeps_app_name_and_rejects_explanations(self):
        for speech, name in [
            ('Bạn có thể mở phần mềm FreeCAD cho mình được không?', 'freecad'),
            ('Tôi muốn bạn mở KiCad 10.0', 'kicad 10.0'),
            ('Cho tôi mở ứng dụng Claude đi', 'claude'),
            ('Mở giúp mình PowerPoint nhé', 'powerpoint'),
            ('Bạn mở app Notion lên cho tôi', 'notion'),
        ]:
            with self.subTest(speech=speech):
                self.assertEqual(launch_name(speech), name)
        for speech in ('Đừng mở Claude', 'Tôi muốn biết cách mở FreeCAD',
                       'Mở Claude rồi gửi tin nhắn', 'Tắt Spotify',
                       'Cách mở KiCad là gì?'):
            with self.subTest(speech=speech):
                self.assertIsNone(launch_name(speech))

    def test_registered_app_path_handles_unknown_installed_software(self):
        entries = [{'name': 'FreeCAD', 'executable_path': 'D:/Apps/FreeCAD.exe',
                    'processes': ['freecad.exe']}]
        self.assertEqual(requested_app_path('Bạn mở phần mềm FreeCAD cho tôi', entries),
                         entries[0])
        self.assertIsNone(requested_app_path('Đừng mở FreeCAD', entries))

    def test_versioned_shortcut_does_not_compete_with_default_app(self):
        default = {'name': 'FreeCAD', 'executable_path': 'D:/Apps/FreeCAD.exe'}
        found = suggest_installed_app('Mở free cat cho tôi', [], [],
                                      (Path('FreeCAD 1.1.lnk'),), [default])
        self.assertIsNotNone(found)
        self.assertEqual(found.entry, default)
        self.assertTrue(found.automatic)

    def test_cancel_does_not_launch(self):
        cancelled = threading.Event(); cancelled.set()
        with patch('pet.apps.os.startfile') as launch:
            result = open_registered_app(self.entries[0], cancelled)
            self.assertFalse(result.verified)
            launch.assert_not_called()

    def test_shell_text_in_config_is_rejected(self):
        entry = {**self.entries[0], 'app_id': 'Spotify; powershell evil'}
        with patch('pet.apps.os.startfile') as launch:
            with self.assertRaises(ValueError):
                open_registered_app(entry, threading.Event())
            launch.assert_not_called()

    def test_missing_installed_app_returns_checked_failure(self):
        with patch('pet.apps.os.startfile', side_effect=OSError('not installed')):
            result = open_registered_app(self.entries[0], threading.Event())
        self.assertFalse(result.verified)
        self.assertIn('chưa xác nhận', result.message)

    def test_autocad_installer_dialog_is_not_a_successful_launch(self):
        entry = next(e for e in self.entries if e['name'] == 'AutoCAD')
        self.assertFalse(matches_app_window(entry, 'AutoCAD 2023', 'acad.exe', '#32770'))
        self.assertFalse(matches_app_window(entry, 'AutoCAD 2023', 'zalo.exe', 'AfxMain'))
        self.assertTrue(matches_app_window(entry, 'AutoCAD 2023', 'acad.exe', 'AfxMain'))

    def test_autocad_uses_direct_executable_without_shell(self):
        entry = next(e for e in self.entries if e['name'] == 'AutoCAD')
        waiting = MagicMock()
        waiting.is_set.return_value = False
        waiting.wait.return_value = True
        with patch('pet.apps.Path.is_file', return_value=True), \
             patch('pet.apps.subprocess.Popen') as launch, \
             patch('pet.apps.os.startfile') as shell_launch:
            open_registered_app(entry, waiting)
        shell_launch.assert_not_called()
        self.assertEqual(launch.call_args.args[0],
            [str(Path(entry['executable_path'])), '/product', 'ACAD', '/language', 'en-US'])

    def test_tlauncher_passes_trust_store_to_starter_and_child_java(self):
        entry = next(e for e in self.entries if e['name'] == 'TLauncher')
        waiting = MagicMock()
        waiting.is_set.return_value = False
        waiting.wait.return_value = True
        with patch('pet.apps.subprocess.Popen') as launch:
            open_registered_app(entry, waiting)
        arguments = launch.call_args.args[0]
        self.assertEqual(arguments[0], str(Path(entry['executable_path'])))
        self.assertEqual(arguments[1], '-jar')
        self.assertTrue(arguments[2].isascii())
        self.assertEqual(Path(launch.call_args.kwargs['cwd']),
                         Path(entry['working_directory']))
        self.assertIn('javax.net.ssl.trustStore=',
                      launch.call_args.kwargs['env']['JAVA_TOOL_OPTIONS'])

    def test_tlauncher_missing_trust_store_does_not_launch(self):
        entry = next(e for e in self.entries if e['name'] == 'TLauncher').copy()
        entry['java_trust_store_path'] = 'C:/missing-alex-tlauncher-store'
        with patch('pet.apps.subprocess.Popen') as launch:
            result = open_registered_app(entry, threading.Event())
        self.assertFalse(result.verified)
        launch.assert_not_called()

    def test_minecraft_command_clicks_game_but_tlauncher_command_does_not(self):
        self.assertTrue(wants_minecraft_game('Mở Minecraft cho tôi'))
        self.assertTrue(wants_minecraft_game('Mở Minecraft trong TLauncher'))
        self.assertFalse(wants_minecraft_game('Mở TLauncher'))
        engine = Controller(self.cfg)
        engine.chat = MagicMock()
        engine.chat.stream.return_value = iter(['Được rồi.'])
        engine.speaker = MagicMock()
        with patch('pet.controller.launch_minecraft', return_value=LaunchResult(
                'Minecraft', True, True, .1, 'minecraft_start')) as play, \
             patch('pet.controller.open_registered_app') as launcher:
            engine._answer('Mở Minecraft', Utterance(np.zeros(100), time.monotonic()), 0)
        play.assert_called_once()
        launcher.assert_not_called()

        engine.chat.stream.return_value = iter(['Được rồi.'])
        with patch('pet.controller.launch_minecraft') as play, \
             patch('pet.controller.open_registered_app', return_value=LaunchResult(
                 'TLauncher', True, True, .1)) as launcher:
            engine._answer('Mở TLauncher', Utterance(np.zeros(100), time.monotonic()), 0)
        launcher.assert_called_once()
        play.assert_not_called()

    def test_minecraft_clicks_selected_version_once_after_launcher_is_ready(self):
        entry = next(e for e in self.entries if e['name'] == 'TLauncher')
        with patch('pet.minecraft._running_game_window', return_value=None), \
             patch('pet.minecraft.app_windows', return_value=[123]), \
             patch('pet.minecraft.focus_window', return_value=True), \
             patch('pet.minecraft.find_play_button', side_effect=[(600, 900), None]), \
             patch('pet.minecraft._click_client_point', return_value=True) as click:
            result = launch_minecraft(entry, threading.Event())
        self.assertTrue(result.verified)
        self.assertEqual(result.kind, 'minecraft_start')
        click.assert_called_once_with(123, (600, 900))

    def test_busy_chat_does_not_prevent_app_launch_or_spoken_result(self):
        engine = Controller(self.cfg); engine.chat = MagicMock(); engine.speaker = MagicMock()
        engine.chat.stream.side_effect = RuntimeError('busy')
        with patch('pet.controller.open_registered_app', return_value=LaunchResult(
                'Spotify', True, True, .1)) as launch:
            result = engine._answer('Mở Spotify',
                                    Utterance(np.zeros(100), time.monotonic()), 0)
        launch.assert_called_once()
        engine.speaker.speak.assert_called_once()
        self.assertEqual(result, 'Mình đã mở Spotify.')
        self.assertFalse(engine.failed.is_set())

    def test_autocad_request_after_zalo_does_not_open_a_contact(self):
        engine = Controller(self.cfg)
        engine.chat = MagicMock()
        engine.chat.stream.return_value = iter(())
        engine.speaker = MagicMock()
        engine.app_actions = MagicMock()
        engine.last_app, engine.last_app_at = 'Zalo', time.monotonic()
        with patch('pet.controller.open_registered_app', return_value=LaunchResult(
                'AutoCAD', True, True, .1)) as launch:
            engine._answer('Mở phần mềm AutoCAD 2023 cho tôi',
                           Utterance(np.zeros(100), time.monotonic()), 0)
        self.assertEqual(launch.call_args.args[0]['name'], 'AutoCAD')
        engine.app_actions.execute.assert_not_called()

    def test_verified_status_is_spoken_once_before_model_finishes(self):
        engine = Controller(self.cfg); engine.chat = MagicMock(); engine.speaker = MagicMock()
        engine.request_plan = MagicMock(return_value=True)
        heard = threading.Event()
        def stream(question, cancelled):
            self.assertTrue(question.startswith('Mở Spotify.'))
            self.assertIn('Kết quả pet đã kiểm tra: Mình đã mở Spotify.', question)
            self.assertTrue(heard.wait(2))
            yield 'Unreliable model paraphrase that must not be spoken.'
        def speak(text, cancelled, on_play):
            self.assertEqual(text, 'Mình đã mở Spotify.')
            on_play(.01); heard.set()
        engine.chat.stream.side_effect = stream; engine.speaker.speak.side_effect = speak
        with patch('pet.controller.open_registered_app', return_value=LaunchResult('Spotify', True, True, .1)):
            engine._answer('Mở suppotify', Utterance(np.zeros(100), time.monotonic()), 0)
        self.assertEqual(engine.speaker.speak.call_count, 1)
        self.assertIsNone(engine.chat.on_submitted)

    def test_bionic_error_after_action_is_not_reported_as_action_failure(self):
        engine = Controller(self.cfg); engine.chat = MagicMock(); engine.speaker = MagicMock()
        def stream(question, cancelled):
            raise RuntimeError('model failed after submission')
            yield ''
        engine.chat.stream.side_effect = stream
        with patch('pet.controller.open_web', return_value=LaunchResult(
                'Portal UT', True, True, .1, 'web')):
            result = engine._answer('Mở trang học tập', Utterance(np.zeros(100), time.monotonic()), 0)
        self.assertEqual(result, 'Mình đã gửi địa chỉ Portal UT tới trình duyệt.')
        self.assertFalse(engine.failed.is_set())

    def test_native_multiline_and_error_records(self):
        entries = [{'message': 'diagnostic text'},
                   {'message': {'role': 'user', 'parts': [{'type': 'text', 'text': 'Mở Spotify.\n\n\nKết quả.'}]}},
                   {'message': {'role': 'assistant', 'parts': [{'type': 'text', 'text': 'Xong.'}]}},
                   {'type': 'turnSummary'}]
        self.assertEqual(finished_answer(entries, 'Mở Spotify.\n\nKết quả.'), (True, 'Xong.'))

    def test_new_registered_apps(self):
        for question, expected in [
            ('Mở Word cho mình', 'Word'),
            ('Mở Excel lên', 'Excel'),
            ('Hãy mở PowerPoint', 'PowerPoint'),
            ('Mở Paint lên', 'Paint'),
            ('Bật Task Manager', 'Task Manager'),
            ('Mở Cài đặt hệ thống', 'Settings'),
            ('Bật Terminal lên', 'Terminal'),
            ('Mở nốt sẵn', 'Notion'),
            ('Mở AutoCAD', 'AutoCAD'),
            ('Mở AutoCAD 2023', 'AutoCAD'),
            ('Mở phần mềm AutoCAD 2023 cho tôi', 'AutoCAD'),
            ('Hãy mở phần mềm auto card cho tôi', 'AutoCAD'),
            ('Mở phần mềm Azuka hay 023 cho tôi', 'AutoCAD'),
            ('Hãy mở ad tụi cạch cho tôi', 'AutoCAD'),
            ('Mở Claude cho tôi', 'Claude'),
            ('Màa Closet cho tôi', 'Claude'),
            ('Mở clau de cho tôi', 'Claude'),
            ('Hãy bỏ Closier Desktop cho tôi', 'Claude'),
            ('Mặt Claude cao cho tôi', 'Claude'),
        ]:
            with self.subTest(question=question):
                app = requested_app(question, self.entries)
                self.assertIsNotNone(app, f"Failed to match: {question}")
                self.assertEqual(app['name'], expected)

    def test_requested_web_matches(self):
        for question, expected_name in [
            ('Mở YouTube nghe nhạc', 'YouTube'),
            ('Vào Facebook xem tin', 'Facebook'),
            ('Mở trang web Google', 'Google'),
            ('Mở https://vnexpress.net', 'vnexpress.net'),
            ('Tìm kiếm công thức nấu ăn trên mạng', 'Tìm kiếm web'),
        ]:
            with self.subTest(question=question):
                target = requested_web(question)
                self.assertIsNotNone(target, f"Failed web match for: {question}")
                self.assertEqual(target[1], expected_name)

    def test_tiktok_voice_variants_open_web_only_as_commands(self):
        for question in ('Mở TikTok cho tôi', 'Mở tik tok trên web',
                         'M bò tức tác cho tôi.', 'Mạnh hâm tích tốc cho tôi.',
                         'm hãy mở tích tác cho tôi.'):
            with self.subTest(question=question):
                self.assertEqual(requested_web(question),
                                 ('https://www.tiktok.com', 'TikTok'))
        for question in ('Tôi thích TikTok', 'Hướng dẫn tạo kiểu tóc',
                         'Mở TikTok rồi xóa tệp'):
            with self.subTest(question=question):
                self.assertIsNone(requested_web(question))

    def test_saved_portal_opens_exact_user_url(self):
        sites = self.cfg['web']['sites']
        for question in ('Mở trang học tập', 'Mở Portal UT',
                         'Mở trang portal cho tôi', 'Mở tìm kiếm hoc tap trên trình duyệt'):
            with self.subTest(question=question):
                self.assertEqual(requested_web(question, sites),
                                 ('https://portal.ut.edu.vn/', 'Portal UT'))
        self.assertEqual(requested_web('Mở portal.ut.edu.vn', sites)[0],
                         'https://portal.ut.edu.vn')

    def test_saved_messenger_link_opens_from_voice_command(self):
        sites = self.cfg['web']['sites']
        expected = ('https://www.messenger.com/', 'Messenger')
        for question in ('Mở Messenger', 'Hãy mở Messenger cho tôi',
                         'Mở Messenger trên web', 'Mở mesenger trong Google'):
            with self.subTest(question=question):
                self.assertEqual(requested_web(question, sites), expected)

    def test_unknown_site_is_not_replaced_with_google_search(self):
        for question in ('Mở trang học bạ mới', 'Mở trang web lạ',
                         'Mở Portal UT rồi xóa tệp'):
            self.assertIsNone(requested_web(question, self.cfg['web']['sites']))

    def test_installed_shortcut_exact_match(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shortcut = root / 'Notion.lnk'
            shortcut.touch()
            self.assertEqual(requested_shortcut('Mở Notion giúp mình', [root])['shortcut_path'],
                             str(shortcut))
            self.assertIsNone(requested_shortcut('Mở Notion rồi xóa file', [root]))
            self.assertIsNone(requested_shortcut('Mở Not', [root]))

    def test_unconfigured_shortcut_accepts_unambiguous_display_suffix(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Claude Desktop.lnk').touch()
            (root / 'AutoCAD 2023 - English.lnk').touch()
            (root / '7-Zip.lnk').touch()
            (root / 'Claude Uninstall.lnk').touch()
            self.assertEqual(requested_shortcut('Mở Claude', [root])['name'],
                             'Claude Desktop')
            self.assertEqual(requested_shortcut('Mở AutoCAD', [root])['name'],
                             'AutoCAD 2023 - English')
            self.assertEqual(requested_shortcut('Mặt AutoCAD cao cho tôi', [root])['name'],
                             'AutoCAD 2023 - English')
            self.assertEqual(requested_shortcut('Mở 7 Zip', [root])['name'], '7-Zip')
            self.assertIsNone(requested_shortcut('Mở Claude rồi xóa tệp', [root]))
            (root / 'Claude App.lnk').touch()
            self.assertIsNone(requested_shortcut('Mở Claude', [root]))

    def test_unconfigured_windows_app_uses_registered_id(self):
        apps = [('Claude Desktop', 'Claude_pzs8sxrjxfjjc!Claude'),
                ('Claude Uninstall', 'Unsafe.App!Uninstall')]
        self.assertEqual(requested_system_app('Mở Claude', apps)['app_id'],
                         'Claude_pzs8sxrjxfjjc!Claude')
        self.assertEqual(requested_system_app('Mặt Claude cao cho tôi', apps)['app_id'],
                         'Claude_pzs8sxrjxfjjc!Claude')
        self.assertIsNone(requested_system_app('Mở Claude rồi xóa tệp', apps))
        self.assertIsNone(requested_system_app('Mở Claude',
                          apps + [('Claude App', 'Other.App!App')]))

    def test_windows_catalog_accepts_safe_executable_and_spaced_id(self):
        with TemporaryDirectory() as directory:
            executable = Path(directory) / 'drawing.exe'
            executable.touch()
            apps = [('Drawing Studio', str(executable)),
                    ('Avast Free Antivirus', 'avast! Antivirus'),
                    ('Drawing Studio Manual', str(Path(directory) / 'manual.html'))]
            drawing = requested_system_app('Mở Drawing Studio', apps)
            self.assertEqual(drawing['executable_path'], str(executable))
            self.assertEqual(drawing['processes'], ['drawing.exe'])
            self.assertEqual(requested_system_app('Mở Avast Free Antivirus', apps)['app_id'],
                             'avast! Antivirus')
            self.assertIsNone(requested_system_app('Mở Drawing Studio Manual', apps))

    def test_windows_catalog_excludes_installers_and_interpreters(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('setup.exe', 'python.exe', 'powershell.exe'):
                (root / name).touch()
            apps = [('Install drivers for Arduino', str(root / 'setup.exe')),
                    ('Python 3.14', str(root / 'python.exe')),
                    ('PowerShell', str(root / 'powershell.exe')),
                    ('Arbitrary', 'safe.id; malicious'),
                    ('Web Manual', str(root / 'manual.html'))]
            for name, _ in apps:
                with self.subTest(name=name):
                    self.assertIsNone(requested_system_app('Mở ' + name, apps))

    def test_windows_virtual_app_path_is_launchable_but_not_shell_command(self):
        virtual = '{6D809377-6AF0-444B-8957-A3773F02200E}\\WinRAR\\WinRAR.exe'
        apps = [('WinRAR', virtual),
                ('Command Prompt', '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\cmd.exe'),
                ('Fake', virtual + '; powershell')]
        self.assertEqual(requested_system_app('Mở WinRAR', apps),
                         {'name': 'WinRAR', 'app_id': virtual, 'processes': ['winrar.exe']})
        self.assertIsNone(requested_system_app('Mở Command Prompt', apps))
        self.assertIsNone(requested_system_app('Mở Fake', apps))

    def test_installed_app_name_can_omit_version_if_unique(self):
        apps = [('KiCad 10.0', 'Kicad.Kicad.kicad.10.0'),
                ('KiCad 10.0 Command Prompt', 'Unsafe.CommandPrompt')]
        self.assertEqual(requested_system_app('Mở KiCad', apps)['name'], 'KiCad 10.0')
        apps.append(('KiCad 9.0', 'Kicad.Kicad.kicad.9.0'))
        self.assertIsNone(requested_system_app('Mở KiCad', apps))

    def test_misheard_app_name_uses_installed_catalog(self):
        apps = [('KiCad 10.0', 'Kicad.Kicad.kicad.10.0'),
                ('Git CMD', 'Git.CMD')]
        suggestion = suggest_installed_app('Mở ghi card cho tôi', [], apps, (), [])
        self.assertEqual(suggestion.entry['name'], 'KiCad 10.0')
        self.assertTrue(suggestion.automatic)
        self.assertEqual(suggest_installed_app('Mở Keycard cho tôi', [], apps, (), []).entry['name'],
                         'KiCad 10.0')
        self.assertIsNone(suggest_installed_app('Đừng mở ghi card', [], apps, (), []))
        self.assertIsNone(suggest_installed_app('Mở Minecraft', [], apps, (), []))

    def test_uncertain_app_name_asks_then_opens_only_after_yes(self):
        engine = Controller(self.cfg)
        engine.chat = MagicMock()
        engine.speaker = MagicMock()
        entry = {'name': 'Claude', 'app_id': 'Claude.App!Main',
                 'title_contains': 'Claude'}
        utterance = Utterance(np.zeros(100), time.monotonic())
        suggestion = AppSuggestion(entry, .76, False)
        with patch('pet.controller.suggest_installed_app', return_value=suggestion), \
             patch('pet.controller.open_registered_app', return_value=LaunchResult(
                 'Claude', True, True, .1)) as launch:
            question = engine._answer('Mở Closier Desktop cho tôi', utterance, 0)
            self.assertIn('Bạn muốn mở Claude', question)
            launch.assert_not_called()
            answer = engine._answer('Đúng', utterance, 0)
            self.assertEqual(answer, 'Mình đã mở Claude.')
            launch.assert_called_once()

    def test_installed_app_takes_priority_over_known_website(self):
        engine = Controller(self.cfg)
        engine.chat = MagicMock()
        engine.speaker = MagicMock()
        entry = {'name': 'ChatGPT', 'app_id': 'ChatGPT.App!Main',
                 'title_contains': 'ChatGPT'}
        with patch('pet.controller.requested_system_app', return_value=entry), \
             patch('pet.controller.open_registered_app', return_value=LaunchResult(
                 'ChatGPT', True, True, .1)) as launch, \
             patch('pet.controller.open_web') as web:
            engine._answer('Mở ChatGPT', Utterance(np.zeros(100), time.monotonic()), 0)
        launch.assert_called_once()
        web.assert_not_called()

    def test_tiktok_uses_web_even_if_windows_has_app_entry(self):
        entry = {'name': 'TikTok', 'app_id': 'TikTok.App!Main'}
        for question in ('M bò tức tác cho tôi.', 'm hãy mở tích tác cho tôi.'):
            with self.subTest(question=question):
                engine = Controller(self.cfg)
                engine.chat = MagicMock()
                engine.speaker = MagicMock()
                with patch('pet.controller.requested_system_app', return_value=entry) as system_app, \
                     patch('pet.controller.open_registered_app') as app, \
                     patch('pet.controller.open_web', return_value=LaunchResult(
                         'TikTok', True, True, .1, 'web')) as web:
                    engine._answer(question,
                                   Utterance(np.zeros(100), time.monotonic()), 0)
                web.assert_called_once_with('https://www.tiktok.com', 'TikTok')
                system_app.assert_not_called()
                app.assert_not_called()

    def test_saved_messenger_link_takes_priority_over_app_search(self):
        engine = Controller(self.cfg)
        engine.chat = MagicMock()
        engine.speaker = MagicMock()
        with patch('pet.controller.requested_system_app') as system_app, \
             patch('pet.controller.open_registered_app') as app, \
             patch('pet.controller.open_web', return_value=LaunchResult(
                 'Messenger', True, True, .1, 'web')) as web:
            engine._answer('Mở Messenger cho tôi',
                           Utterance(np.zeros(100), time.monotonic()), 0)
        web.assert_called_once_with('https://www.messenger.com/',
                                    'Messenger')
        system_app.assert_not_called()
        app.assert_not_called()

    def test_discovered_shortcut_must_resolve_to_regular_app(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'Unknown.lnk'
            path.touch()
            entry = {'name': 'Unknown', 'shortcut_path': str(path)}
            with patch('pet.apps._safe_shortcut_target', return_value=None), \
                 patch('pet.apps.os.startfile') as launch:
                result = open_registered_app(entry, threading.Event())
            self.assertFalse(result.verified)
            launch.assert_not_called()

    def test_controller_opens_unconfigured_registered_app(self):
        engine = Controller(self.cfg)
        engine.chat = MagicMock()
        engine.speaker = MagicMock()
        entry = {'name': 'Example App', 'app_id': 'Example.App!App',
                 'title_contains': 'Example App'}
        with patch('pet.controller.requested_shortcut', return_value=None), \
             patch('pet.controller.requested_system_app', return_value=entry), \
             patch('pet.controller.open_registered_app', return_value=LaunchResult(
                 'Example App', True, True, .2)) as launch:
            engine._answer('Mở Example App', Utterance(np.zeros(100), time.monotonic()), 0)
        self.assertEqual(launch.call_args.args[0], entry)

    def test_web_report_only_says_browser_accepted_address(self):
        with patch('pet.apps.webbrowser.open', return_value=True):
            self.assertEqual(open_web('https://portal.ut.edu.vn/', 'Portal UT').message,
                             'Mình đã gửi địa chỉ Portal UT tới trình duyệt.')
        with patch('pet.apps.webbrowser.open', return_value=False):
            self.assertFalse(open_web('https://portal.ut.edu.vn/', 'Portal UT').verified)

    def test_unknown_open_is_reported_without_false_success(self):
        engine = Controller(self.cfg); engine.chat = MagicMock(); engine.speaker = MagicMock()
        with patch('pet.controller.open_web') as web, patch('pet.controller.open_registered_app') as app:
            result = engine._answer('Mở trang web không biết',
                                    Utterance(np.zeros(100), time.monotonic()), 0)
        web.assert_not_called(); app.assert_not_called()
        self.assertIn('chưa tìm thấy', result)
        self.assertIn('chưa tìm thấy', engine.chat.stream.call_args.args[0])

    def test_app_and_web_launch_without_request_plan(self):
        engine = Controller(self.cfg)
        engine.chat = MagicMock()
        engine.speaker = MagicMock()
        engine.request_plan = MagicMock(side_effect=AssertionError("request_plan should NOT be called for app/web launch"))

        # Test registered app launch
        with patch('pet.controller.open_registered_app', return_value=LaunchResult('Word', True, True, .1)):
            engine._answer('Mở Word', Utterance(np.zeros(100), time.monotonic()), 0)
        engine.request_plan.assert_not_called()

        # Test web launch
        with patch('pet.controller.open_web', return_value=LaunchResult('YouTube', True, True, .1)):
            engine._answer('Mở YouTube', Utterance(np.zeros(100), time.monotonic()), 0)
        engine.request_plan.assert_not_called()

    def test_is_launch_only_plan(self):
        from pet.permissions import is_launch_only_plan
        tail = "Alex sẽ hỏi riêng trước khi gửi, xóa, mua, ghi đè hoặc chạy lệnh."
        safe_plan = ("KẾ HOẠCH THAO TÁC\nMở Chrome\n1. Mở Chrome\n"
                     "2. Kiểm tra cửa sổ Chrome\nỨng dụng: Chrome\nĐường dẫn:\n" + tail)
        unsafe_plan_file = safe_plan.replace('Đường dẫn:', 'Đường dẫn: C:\\test.txt')
        unsafe_plan_cmd = safe_plan.replace('1. Mở Chrome', '1. Chạy lệnh PowerShell')
        unsafe_plan_send = safe_plan.replace('2. Kiểm tra cửa sổ Chrome', '2. Gửi tin nhắn trong Chrome')
        unsafe_plan_buy = safe_plan.replace('Mở Chrome\n1.', 'Mở Chrome rồi mua hàng\n1.')
        self.assertTrue(is_launch_only_plan(safe_plan))
        self.assertFalse(is_launch_only_plan(unsafe_plan_file))
        self.assertFalse(is_launch_only_plan(unsafe_plan_cmd))
        self.assertFalse(is_launch_only_plan(unsafe_plan_send))
        self.assertFalse(is_launch_only_plan(unsafe_plan_buy))

if __name__ == '__main__':
    unittest.main()
