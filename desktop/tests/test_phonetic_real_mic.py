import unittest
from pet.apps import _phonetic_key, suggest_installed_app


class RealMicPhoneticTests(unittest.TestCase):
    apps=[{'name':'KiCad'}, {'name':'Zalo'}, {'name':'Calculator'}]

    def suggest(self, text, apps=None):
        diagnostic={}
        result=suggest_installed_app(text, apps or self.apps, apps=[],shortcuts=(),app_paths=[],diagnostics=diagnostic)
        return result,diagnostic

    def test_two_actual_transcripts_resolve_installed_kicad(self):
        for text in ('Mở KitKat cho tôi.','Hãy mở KitKat cho tôi.'):
            with self.subTest(text=text):
                result,trace=self.suggest(text)
                self.assertEqual(result.entry['name'],'KiCad')
                self.assertTrue(result.automatic)
                self.assertEqual(trace['score'],1.0)

    def test_similar_registered_app_prevents_automatic_guess(self):
        result,trace=self.suggest('Mở KitKat cho tôi.',[{'name':'KiCad'},{'name':'KitKat'}])
        self.assertIsNone(result)
        self.assertEqual(trace['score'],trace['runner_up'])

    def test_no_launch_for_conversation_negation_or_multiple_actions(self):
        for text in ('Tôi đang ăn KitKat.', 'Đừng mở KitKat', 'Mở KitKat rồi xóa tệp'):
            self.assertIsNone(self.suggest(text)[0])

    def test_no_global_syllable_rewrite(self):
        for text in ('kit','kat','toolkit'):
            self.assertEqual(_phonetic_key(text),text)
        self.assertEqual(_phonetic_key('KiCad'),'kicad')
        self.assertEqual(_phonetic_key('KitKat'),'kicad')


if __name__=='__main__':unittest.main(verbosity=2)
