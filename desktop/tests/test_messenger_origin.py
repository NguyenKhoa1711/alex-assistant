import unittest
from pet.messaging_driver import MessengerUiDriver


class MessengerOriginTests(unittest.TestCase):
    def setUp(self): self.driver = MessengerUiDriver()

    def test_untrusted_missing_or_non_document_url_is_rejected(self):
        cases = (
            {'role': 'document', 'url': 'https://www.messenger.com.evil.example/thread'},
            {'role': 'document', 'url': 'https://messenger.com.evil.example/'},
            {'role': 'document', 'url': 'https://facebook.com/messages-evil'},
            {'role': 'document', 'url': 'https://messenger.com@evil.example/'},
            {'role': 'document', 'url': 'http://www.messenger.com/'},
            {'role': 'document', 'url': 'https://messenger.com:444/'},
            {'role': 'main'},
            {'role': 'link', 'url': 'https://messenger.com/'},
        )
        for tree in cases:
            with self.subTest(tree=tree), self.assertRaises(RuntimeError):
                self.driver._verify_messenger_surface({'tree': tree})

    def test_exact_https_origins_and_message_paths(self):
        for url in ('https://www.messenger.com/t/123', 'https://messenger.com/',
                    'https://www.facebook.com/messages/t/123', 'https://facebook.com/messages'):
            with self.subTest(url=url):
                self.driver._verify_messenger_surface({'tree': {'role': 'document', 'url': url}})

    def test_untrusted_second_document_cannot_be_hidden(self):
        with self.assertRaises(RuntimeError):
            self.driver._verify_messenger_surface({'tree': {'role':'window','children':[
                {'role':'document','url':'https://messenger.com/'},
                {'role':'document','url':'https://evil.example/'},
            ]}})
