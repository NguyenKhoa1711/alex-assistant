from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pet.study_helper import (
    RegionSnipOverlay,
    parse_api_keys,
    pixmap_to_jpeg_base64,
    solve_problem_gemini_vision,
    solve_problem_groq_vision,
)


class StudyHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_parse_api_keys_splits_newlines_and_commas(self):
        keys = parse_api_keys('gsk_one, gsk_two\ngsk_three\n gsk_one ')
        self.assertEqual(keys, ['gsk_one', 'gsk_two', 'gsk_three'])

    def test_pixmap_to_jpeg_base64_encodes_image(self):
        img = QImage(320, 100, QImage.Format.Format_RGB32)
        img.fill(QColor('white'))
        p = QPainter(img)
        p.setPen(QColor('black'))
        p.setFont(QFont('Arial', 18))
        p.drawText(15, 60, '2x + 4 = 10')
        p.end()
        b64 = pixmap_to_jpeg_base64(QPixmap.fromImage(img))
        self.assertTrue(len(b64) > 100)

    def test_groq_vision_rotates_to_second_key_on_429(self):
        img = QImage(200, 80, QImage.Format.Format_RGB32)
        img.fill(QColor('white'))
        pix = QPixmap.fromImage(img)

        resp_429 = MagicMock(status_code=429)
        resp_200 = MagicMock(status_code=200)
        resp_200.json.return_value = {
            'choices': [{'message': {'content': '2x = 6 => x = 3\nĐÁP ÁN: x = 3'}}]
        }

        fake_client = MagicMock()
        fake_client.__enter__.return_value = fake_client
        fake_client.post.side_effect = [resp_429, resp_200]

        with patch('pet.study_helper.extract_text_windows_ocr', return_value='Solve: 2x + 4 = 10'), \
             patch('pet.study_helper.httpx.Client', return_value=fake_client):
            short_ans, full_reply = solve_problem_groq_vision(pix, keys=['gsk_bad', 'gsk_good'])

        self.assertEqual(short_ans, 'x = 3')
        self.assertIn('2x = 6', full_reply)
        self.assertEqual(fake_client.post.call_count, 2)

    def test_gemini_vision_rotates_and_shares_load_across_keys(self):
        img = QImage(200, 80, QImage.Format.Format_RGB32)
        img.fill(QColor('white'))
        pix = QPixmap.fromImage(img)

        resp_429 = MagicMock(status_code=429)
        resp_200 = MagicMock(status_code=200)
        resp_200.json.return_value = {
            'candidates': [{'content': {'parts': [{'text': 'Tính tích phân ra 12\nĐÁP ÁN: C. 12'}]}}]
        }

        fake_client = MagicMock()
        fake_client.__enter__.return_value = fake_client
        fake_client.post.side_effect = [resp_429, resp_200]

        with patch('pet.study_helper.httpx.Client', return_value=fake_client):
            short_ans, full_reply = solve_problem_gemini_vision(pix, keys=['AIza_k1', 'AIza_k2'])

        self.assertEqual(short_ans, 'C. 12')
        self.assertIn('tích phân', full_reply)
        self.assertEqual(fake_client.post.call_count, 2)

    def test_region_overlay_escape_cancels(self):
        overlay = RegionSnipOverlay()
        cancelled = []
        overlay.cancelled.connect(lambda: cancelled.append(True))
        QTest.keyClick(overlay, Qt.Key.Key_Escape)
        self.assertEqual(cancelled, [True])


if __name__ == '__main__':
    unittest.main()
