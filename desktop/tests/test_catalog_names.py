import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pet.apps import (requested_system_app, requested_shortcut, requested_app_path,
                      _matches_installed_window, _product_icon_entry)


class InstalledAppNameTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.exe=self.root/'git-gui.exe'
        self.exe.touch()
        self.catalog=[('Git GUI',str(self.exe)),
                      ('Game Bar','Microsoft.XboxGamingOverlay_8wekyb3d8bbwe!App'),
                      ('Uninstall App','Uninstall.App!App')]

    def test_exact_names_containing_gui_or_game(self):
        self.assertEqual(requested_system_app('Mở Git GUI cho tôi',self.catalog)['name'],'Git GUI')
        self.assertEqual(requested_system_app('Mở phần mềm Git GUI cho tôi',self.catalog)['name'],'Git GUI')
        self.assertEqual(requested_system_app('Mở Game Bar cho tôi',self.catalog)['name'],'Game Bar')
        self.assertEqual(requested_system_app('Mở ứng dụng Game Bar',self.catalog)['name'],'Game Bar')

    def test_same_name_with_two_targets_is_ambiguous(self):
        options=[('Quick Assist','First.App!App'),('Quick Assist','Second.App!App')]
        self.assertIsNone(requested_system_app('Mở Quick Assist',options))

    def test_compound_and_unsafe_commands_are_not_opened(self):
        for text in ('Mở Git GUI rồi xóa file', 'Mở Git GUI và tắt máy',
                     'Mở Git GUI; powershell', 'Đừng mở Git GUI', 'Mở Uninstall App'):
            with self.subTest(text=text):
                self.assertIsNone(requested_system_app(text,self.catalog))

    def test_exact_shortcuts_and_app_paths(self):
        (self.root/'Git GUI.lnk').touch()
        (self.root/'Game Bar.lnk').touch()
        self.assertEqual(requested_shortcut('Mở Git GUI', [self.root])['name'],'Git GUI')
        self.assertEqual(requested_shortcut('Mở Game Bar', [self.root])['name'],'Game Bar')
        paths=[{'name':'Git GUI','executable_path':str(self.exe),'processes':['git-gui.exe']}]
        self.assertEqual(requested_app_path('Mở Git GUI',paths)['name'],'Git GUI')

    def test_installed_product_icon_requires_matching_safe_executable(self):
        exe=self.root/'CustomCursor.exe'
        exe.touch()
        entry=_product_icon_entry('Custom Cursor 1.0.25',f'"{exe}",0')
        self.assertEqual(entry['name'],'Custom Cursor 1.0.25')
        self.assertEqual(requested_app_path('Mở Custom Cursor',[entry]),entry)
        disk=self.root/'DiskGenius.exe';disk.touch()
        disk_entry=_product_icon_entry('DiskGenius V6.2.0',str(disk))
        self.assertEqual(requested_app_path('Mở DiskGenius',[disk_entry]),disk_entry)
        self.assertIsNone(_product_icon_entry('Another App',str(exe)))
        self.assertIsNone(_product_icon_entry('Custom Cursor Update',str(exe)))
        self.assertIsNone(_product_icon_entry('Custom Cursor',f'"{exe}" --delete'))
        setup=self.root/'Setup.exe';setup.touch()
        self.assertIsNone(_product_icon_entry('Setup',str(setup)))

    def test_small_talk_never_scans_installed_apps(self):
        with patch('pet.apps._apps_folder',side_effect=AssertionError), \
             patch('pet.apps._installed_shortcuts',side_effect=AssertionError), \
             patch('pet.apps._app_paths',side_effect=AssertionError):
            self.assertIsNone(requested_system_app('Chào bạn'))
            self.assertIsNone(requested_shortcut('Chào bạn'))
            self.assertIsNone(requested_app_path('Chào bạn'))

    def test_launcher_child_requires_product_title_and_install_root(self):
        entry={'name':'Git GUI','executable_path':r'D:\Git\cmd\git-gui.exe',
               'allow_install_window_match':True}
        self.assertTrue(_matches_installed_window(entry,'Git Gui',r'D:\Git\mingw64\bin\wish.exe','TkTopLevel'))
        self.assertFalse(_matches_installed_window(entry,'Another window',r'D:\Git\mingw64\bin\wish.exe','TkTopLevel'))
        self.assertFalse(_matches_installed_window(entry,'Git GUI',r'D:\Other\wish.exe','TkTopLevel'))
        self.assertFalse(_matches_installed_window(entry,'Git GUI',r'D:\Git\mingw64\bin\wish.exe','#32770'))
        self.assertFalse(_matches_installed_window(entry,'Git GUI',r'D:\Git\mingw64\bin\powershell.exe','Window'))
        unrelated={'name':'Example','executable_path':r'C:\Program Files\AppA\launcher.exe',
                   'allow_install_window_match':True}
        self.assertFalse(_matches_installed_window(unrelated,'Example',r'C:\Program Files\AppB\other.exe','Window'))
        self.assertFalse(_matches_installed_window({'name':'Git GUI','executable_path':r'D:\Git\cmd\git-gui.exe'},
                                                   'Git GUI',r'D:\Git\mingw64\bin\wish.exe','TkTopLevel'))

    def test_controller_routes_exact_registered_gui_name_to_launcher(self):
        import time
        import numpy as np
        from unittest.mock import MagicMock
        from pet.audio import Utterance
        from pet.apps import LaunchResult
        from pet.config import load_config
        from pet.controller import Controller
        from pet.llm import LocalChat
        with patch('pet.llm.httpx.Client'):
            engine=Controller(load_config())
        self.addCleanup(engine.local_chat._client.close)
        self.addCleanup(engine.gemini_chat._client.close)
        engine.chat=MagicMock(spec=LocalChat)
        engine.speaker=MagicMock()
        with patch('pet.apps._apps_folder',return_value=self.catalog), \
             patch('pet.controller.open_registered_app',return_value=LaunchResult('Git GUI',True,True,.1)) as launch:
            engine._answer('Mở Git GUI cho tôi',Utterance(np.zeros(100),time.monotonic()),0)
        self.assertEqual(launch.call_args.args[0]['name'],'Git GUI')

    def test_controller_routes_exact_game_bar_name_to_launcher(self):
        import time
        import numpy as np
        from unittest.mock import MagicMock
        from pet.audio import Utterance
        from pet.apps import LaunchResult
        from pet.config import load_config
        from pet.controller import Controller
        from pet.llm import LocalChat
        with patch('pet.llm.httpx.Client'):
            engine=Controller(load_config())
        self.addCleanup(engine.local_chat._client.close)
        self.addCleanup(engine.gemini_chat._client.close)
        engine.chat=MagicMock(spec=LocalChat)
        engine.speaker=MagicMock()
        with patch('pet.apps._apps_folder',return_value=self.catalog), \
             patch('pet.controller.open_registered_app',return_value=LaunchResult('Game Bar',True,True,.1)) as launch:
            engine._answer('Mở Game Bar cho tôi',Utterance(np.zeros(100),time.monotonic()),0)
        self.assertEqual(launch.call_args.args[0]['name'],'Game Bar')


if __name__=='__main__': unittest.main()
