import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication
from pet import study_helper as study


class StudyFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def pix(self):
        image=QImage(240,120,QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        return QPixmap.fromImage(image)

    def test_gemini_exception_still_uses_configured_groq(self):
        with patch.object(study,'load_gemini_study_keys',return_value=['fake']), \
             patch.object(study,'load_groq_keys',return_value=['fake']), \
             patch.object(study,'solve_problem_gemini_vision',side_effect=OSError('synthetic')), \
             patch.object(study,'solve_problem_groq_vision',return_value=('B','ĐÁP ÁN: B')) as groq:
            short,full=study.solve_problem_smart(self.pix())
        self.assertEqual(short,'B')
        self.assertIn('OCR dự phòng',full)
        groq.assert_called_once()

    def test_groq_truncated_answer_is_not_presented_as_complete(self):
        response=MagicMock(status_code=200)
        response.json.return_value={'choices':[{'finish_reason':'length','message':{'content':'ĐÁP ÁN: B'}}]}
        client=MagicMock();client.__enter__.return_value=client;client.post.return_value=response
        with patch.object(study,'extract_text_windows_ocr',return_value='synthetic question'), \
             patch.object(study.httpx,'Client',return_value=client):
            short,full=study.solve_problem_groq_vision(self.pix(),keys=['fake'])
        self.assertIn('bị cắt',short)
        self.assertIn('bị cắt',full)
        self.assertEqual(client.post.call_count,1)

    def test_empty_groq_choice_moves_to_second_key(self):
        empty=MagicMock(status_code=200);empty.json.return_value={'choices':[]}
        good=MagicMock(status_code=200);good.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':'ĐÁP ÁN: B'}}]}
        client=MagicMock();client.__enter__.return_value=client;client.post.side_effect=[empty,good]
        with patch.object(study,'_GROQ_KEY_INDEX',0), \
             patch.object(study,'extract_text_windows_ocr',return_value='synthetic question'), \
             patch.object(study.httpx,'Client',return_value=client):
            short,_=study.solve_problem_groq_vision(self.pix(),keys=['fake1','fake2'])
        self.assertEqual(short,'B')
        self.assertEqual(client.post.call_count,2)

    def test_cooldown_produces_useful_error_without_request(self):
        client=MagicMock();client.__enter__.return_value=client
        with patch.object(study,'_KEY_COOLDOWN_UNTIL',{'fake':float('inf')}), \
             patch.object(study.httpx,'Client',return_value=client):
            short,_=study.solve_problem_gemini_vision(self.pix(),keys=['fake'])
        self.assertIn('tạm chờ sau khi vượt hạn mức',short)
        client.post.assert_not_called()
