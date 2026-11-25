from __future__ import annotations

import unittest

from pet.multilang_tts import (
    convert_hanzi_span_to_vi,
    convert_pinyin_token_to_vi,
    prepare_multilang_speech,
    tag_english_for_vieneu,
)
from pet.wake import SentenceBuffer, speech_text


class MultilangTTSTests(unittest.TestCase):
    def test_vietnamese_name_and_words_stay_intact(self) -> None:
        self.assertEqual(speech_text('Mình là **Alex**!', 'Alex', 'A lếch'), 'Mình là A lếch!')
        s = 'Từ "go" nghĩa là đi, "do" là làm, "to" là tới.'
        cleaned = speech_text(s, 'Alex', 'A lếch')
        self.assertIn('làm', cleaned)
        self.assertNotIn('là m', cleaned)

    def test_english_sentences_keep_alex_and_lowercase_all_caps_words(self) -> None:
        s = "Hello! My name is Alex, nice to meet you. I LOVE YOU SO MUCH!"
        cleaned = speech_text(s, 'Alex', 'A lếch')
        self.assertIn('My name is Alex', cleaned)
        self.assertIn('love you so much', cleaned)
        self.assertNotIn('LOVE', cleaned)
        tagged = tag_english_for_vieneu(cleaned)
        self.assertIn('<en>my name is alex</en>', tagged)
        self.assertIn('<en>nice to meet you</en>', tagged)
        self.assertIn('<en>i love you so much</en>', tagged)

    def test_quoted_english_homographs_and_acronyms_tagged_for_vieneu(self) -> None:
        s = 'Từ "go" nghĩa là đi, "do" là làm, "to" là tới, "in" là trong, "on" là trên, URL và PDF.'
        tagged = tag_english_for_vieneu(prepare_multilang_speech(s, 'Alex', 'A lếch'))
        self.assertIn('<en>go</en>', tagged)
        self.assertIn('<en>do</en>', tagged)
        self.assertIn('<en>to</en>', tagged)
        self.assertIn('<en>in</en>', tagged)
        self.assertIn('<en>on</en>', tagged)
        self.assertIn('<en>u r l</en>', tagged)
        self.assertIn('<en>p d f</en>', tagged)

    def test_ipa_slashes_stripped_cleanly(self) -> None:
        s = "Từ 'hello' phát âm là /həˈloʊ/, nghĩa là xin chào."
        cleaned = speech_text(s, 'Alex', 'A lếch')
        self.assertNotIn('həˈloʊ', cleaned)
        self.assertNotIn('/', cleaned)
        self.assertIn('xin chào', cleaned)

    def test_chinese_hanzi_and_pinyin_deduplicated_and_converted(self) -> None:
        s = 'Tiếng Trung xin chào là 你好 (Nǐ hǎo), cảm ơn là 谢谢 (Xièxie), tạm biệt là 再见 (Zàijiàn).'
        cleaned = speech_text(s, 'Alex', 'A lếch')
        self.assertNotIn('你好', cleaned)
        self.assertNotIn('谢谢', cleaned)
        self.assertNotIn('再见', cleaned)
        self.assertEqual(cleaned.count('hảo'), 1)
        self.assertIn('ní hảo', cleaned)
        self.assertIn('xía xịa', cleaned)
        self.assertIn('chái chiến', cleaned)

    def test_pure_hanzi_converted_without_dropping(self) -> None:
        s = '你好吗？我很好，谢谢！我爱你。对不起，没关系。'
        cleaned = speech_text(s, 'Alex', 'A lếch')
        self.assertTrue(len(cleaned) > 20)
        self.assertIn('ní hảo ma', cleaned)
        self.assertIn('uố khấn hảo', cleaned)
        self.assertIn('uổ ái nỉ', cleaned)
        self.assertIn('tuấy pu chỉ', cleaned)
        self.assertIn('mấy quan xi', cleaned)

    def test_pinyin_tokens_segmented_and_converted(self) -> None:
        self.assertEqual(convert_pinyin_token_to_vi('Xièxie'), 'xía xịa')
        self.assertEqual(convert_pinyin_token_to_vi('Duìbuqǐ'), 'tuấy pu chỉ')
        self.assertEqual(convert_pinyin_token_to_vi('Zàijiàn'), 'chái chiến')
        self.assertEqual(convert_pinyin_token_to_vi("Wǎn'ān"), 'oản an')
        self.assertEqual(convert_hanzi_span_to_vi('你好'), 'ní hảo')

    def test_sentence_buffer_splits_cjk_punctuation(self) -> None:
        buf = SentenceBuffer()
        chunks = buf.add('你好吗？我很好，谢谢！再见。', final=True)
        self.assertEqual(chunks, ['你好吗？', '我很好，谢谢！再见。'])

    def test_sentence_buffer_keeps_later_chunks_whole(self) -> None:
        buf = SentenceBuffer()
        out = buf.add('Chào bạn. Hôm nay trời đẹp. Mình đi dạo nhé. '
                      'Công viên gần nhà có nhiều cây xanh và hồ nước rất mát. Đi thôi!')
        out += buf.add('', final=True)
        self.assertEqual(out[0], 'Chào bạn.')
        self.assertLessEqual(len(out), 4)
        self.assertEqual(' '.join(out), 'Chào bạn. Hôm nay trời đẹp. Mình đi dạo nhé. '
                         'Công viên gần nhà có nhiều cây xanh và hồ nước rất mát. Đi thôi!')


if __name__ == '__main__':
    unittest.main()
