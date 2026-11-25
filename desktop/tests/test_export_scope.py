import ast
from pathlib import Path
import unittest
from unittest.mock import MagicMock

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from pet.app_window import AlexAppWindow
from tests.test_app_window import FakeEngine

ROOT=Path(__file__).parents[1]


class ExportScopeTests(unittest.TestCase):
    def test_no_phone_or_station_modules_or_top_level_packages(self):
        for name in ('mobile.py','unlock.py','pc_control.py','pc_control_panel.py','pc_control_service.py'):
            self.assertFalse((ROOT/'pet'/name).exists(),name)
        for name in ('android','robot','windows-unlock'):
            self.assertFalse((ROOT.parent/name).exists(),name)

    def test_python_modules_do_not_import_excluded_features(self):
        banned={'mobile','unlock','pc_control','pc_control_panel','pc_control_service'}
        for path in (ROOT/'pet').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
                if isinstance(node,ast.ImportFrom):
                    self.assertNotIn((node.module or '').split('.')[-1],banned,str(path))

    def test_dashboard_retains_chat_and_has_no_station_or_phone_navigation(self):
        app=QApplication.instance() or QApplication([])
        engine=FakeEngine();pet=MagicMock()
        pet.windowIcon.return_value=QIcon()
        window=AlexAppWindow(engine,pet)
        try:
            self.assertIsNotNone(window.chat_page)
            self.assertFalse(hasattr(window,'control_nav'))
            self.assertFalse(hasattr(window,'control_page'))
            window._show_page('chat')
            self.assertIs(window.pages.currentWidget(),window.chat_page)
        finally:
            window.hide();window.avatar.robot.close();window.deleteLater();app.processEvents()

    def test_study_hotkeys_and_helper_are_present(self):
        self.assertTrue((ROOT/'pet/study_helper.py').is_file())
        text=(ROOT/'pet/window.py').read_text(encoding='utf-8')
        self.assertIn('Ctrl+Shift+G',text)
        self.assertIn('solve_fullscreen_instant',text)


if __name__=='__main__':unittest.main()
