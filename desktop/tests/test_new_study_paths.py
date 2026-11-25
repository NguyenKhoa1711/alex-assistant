import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication
from pet import study_helper as study


class StudyPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def pix(self):
        image = QImage(240, 120, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        return QPixmap.fromImage(image)

    def test_gemini_fallback_to_configured_groq_on_provider_failure(self):
        with patch.object(study, 'load_gemini_study_keys', return_value=['dummy']), \
             patch.object(study, 'load_groq_keys', return_value=['dummy2']), \
             patch.object(study, 'solve_problem_gemini_vision', return_value=('Tất cả Gemini key đều lỗi hoặc hết lượt (HTTP 429).',)*2), \
             patch.object(study, 'solve_problem_groq_vision', return_value=('x = 3', 'Lời giải: x = 3')) as groq:
            short, full = study.solve_problem_smart(self.pix())
        self.assertEqual(short, 'x = 3')
        self.assertIn('OCR dự phòng', full)
        groq.assert_called_once()

    def test_gemini_success_does_not_call_groq(self):
        with patch.object(study, 'load_gemini_study_keys', return_value=['dummy']), \
             patch.object(study, 'solve_problem_gemini_vision', return_value=('x = 3', 'x = 3')), \
             patch.object(study, 'load_groq_keys') as groq:
            self.assertEqual(study.solve_problem_smart(self.pix()), ('x = 3', 'x = 3'))
        groq.assert_not_called()

    def test_truncated_gemini_does_not_present_answer_as_complete(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {'candidates': [{'finishReason': 'MAX_TOKENS', 'content': {
            'parts': [{'text': 'ĐÁP ÁN: x = 3'}]}}]}
        client = MagicMock(); client.__enter__.return_value = client; client.post.return_value = response
        with patch.object(study.httpx, 'Client', return_value=client):
            short, full = study.solve_problem_gemini_vision(self.pix(), keys=['dummy'])
        self.assertIn('bị cắt', short)
        self.assertIn('bị cắt', full)
        request = client.post.call_args.kwargs['json']
        self.assertNotIn('thinkingBudget', str(request))

    def test_prompt_says_not_to_guess_missing_or_unclear_information(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {'candidates': [{'content': {'parts': [{'text': 'Ảnh mờ.'}]}}]}
        client = MagicMock(); client.__enter__.return_value = client; client.post.return_value = response
        with patch.object(study.httpx, 'Client', return_value=client):
            study.solve_problem_gemini_vision(self.pix(), keys=['dummy'])
        req = client.post.call_args.kwargs['json']
        prompt = req['contents'][0]['parts'][0]['text']
        self.assertIn('không đoán', prompt)
        self.assertIn('thiếu dữ kiện', prompt)
