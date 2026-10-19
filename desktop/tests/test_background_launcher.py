import json,unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import httpx
from pet.launcher import open_bionic
from pet.bionic import BionicChat,active_session,finished_answer,turn_error


class BackgroundLauncherTests(unittest.TestCase):
    def test_ready_bridge_never_shows_or_launches_window(self):
        with patch('pet.launcher.is_bionic_cdp_ready',return_value=True), \
             patch('pet.launcher.show_existing_window') as show, \
             patch('pet.launcher.subprocess.Popen') as popen:
            open_bionic(show=False)
        show.assert_not_called(); popen.assert_not_called()

    def test_cold_background_launch_hides_native_window_and_waits_for_bridge(self):
        import subprocess
        with patch('pet.launcher.is_bionic_cdp_ready',side_effect=[False,False,True]), \
             patch('pet.launcher.show_existing_window') as show, \
             patch('pet.launcher.bionic_executable',return_value=Path('Bionic.exe')), \
             patch('pet.launcher.time.sleep'),patch('pet.launcher.subprocess.Popen') as popen:
            open_bionic(9223,show=False)
        show.assert_not_called(); popen.assert_called_once()
        options=popen.call_args.kwargs
        self.assertTrue(options['startupinfo'].dwFlags & subprocess.STARTF_USESHOWWINDOW)
        self.assertEqual(options['startupinfo'].wShowWindow,0)
        self.assertIn('--remote-debugging-address=127.0.0.1',popen.call_args.args[0])

    def test_explicit_menu_restores_existing_window_without_relaunch(self):
        with patch('pet.launcher.show_existing_window',return_value=True) as show, \
             patch('pet.launcher.subprocess.Popen') as popen:
            open_bionic()
        show.assert_called_once(); popen.assert_not_called()

    def test_explicit_cold_open_waits_for_visible_window(self):
        with patch('pet.launcher.is_bionic_cdp_ready',return_value=False), \
             patch('pet.launcher.show_existing_window',side_effect=[False,False,True]) as show, \
             patch('pet.launcher.bionic_executable',return_value=Path('Bionic.exe')), \
             patch('pet.launcher.time.sleep'),patch('pet.launcher.subprocess.Popen') as popen:
            open_bionic(show=True)
        self.assertEqual(show.call_count,3);popen.assert_called_once()

    def test_voice_recovery_requests_background_bridge(self):
        renderer=MagicMock()
        renderer.evaluate.side_effect=[False,1,'ready']
        chat=BionicChat({'bridge_port':9223,'require_local_model':False})
        with patch('pet.bionic.Renderer',side_effect=[httpx.ConnectError('offline'),renderer]), \
             patch('pet.bionic.active_session',return_value=('project','session')), \
             patch('pet.launcher.open_bionic') as launch:
            self.assertEqual(chat.check_ready(),('project','session'))
        launch.assert_called_once_with(9223,show=False)
        renderer.close.assert_called_once()

    def test_state_rewrite_retries_read_without_resubmitting(self):
        project='d49037d8-47f4-5808-9028-c707de117f8f'
        session='49627c44-94b6-4a14-b5ab-afded8a16b6d'
        doc={'tabLayouts':{'bionic.sessions':{'type':'pane','active':0,
              'tabs':[f'bionicSession:v2:{project}:model:{session}']}}}
        directory=MagicMock();file=MagicMock();directory.glob.return_value=[file]
        file.read_text.side_effect=['',json.dumps(doc)]
        with patch('pet.bionic.time.sleep') as wait:
            self.assertEqual(active_session(directory),(project,session))
        self.assertEqual(file.read_text.call_count,2);wait.assert_called_once_with(.05)

    def test_invalid_state_fails_after_bounded_read_retries(self):
        directory=MagicMock();file=MagicMock();directory.glob.return_value=[file]
        file.read_text.return_value=''
        with patch('pet.bionic.time.sleep') as wait:
            with self.assertRaisesRegex(RuntimeError,'trạng thái chat'):
                active_session(directory)
        self.assertEqual(file.read_text.call_count,4);self.assertEqual(wait.call_count,3)

    def test_hidden_internal_compaction_note_does_not_lose_answer_or_error(self):
        def message(role,text):
            return {'type':'message','message':{'role':role,'parts':[{'type':'text','text':text}]}}
        note=message('user','Internal compaction completed')
        note.update(hidden=True,source={'type':'ngModule','ngModule':'lmstudio/context-compaction-v1'})
        note['message']['noReplayPostCompaction']=True
        entries=[message('user','Hai cộng ba?'),note,message('assistant','Bằng năm.'),{'type':'turnSummary'}]
        self.assertEqual(finished_answer(entries,'Hai cộng ba?'),(True,'Bằng năm.'))
        self.assertIsNotNone(turn_error(entries[:2]+[{'type':'error'}],'Hai cộng ba?'))
        # A real user's second message must still stop matching the old turn.
        note['hidden']=False
        self.assertEqual(finished_answer(entries,'Hai cộng ba?'),(False,''))
        note['hidden']=True;note['source']['ngModule']='other'
        self.assertEqual(finished_answer(entries,'Hai cộng ba?'),(False,''))


if __name__=='__main__': unittest.main()
