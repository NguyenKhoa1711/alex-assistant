import unittest

from desktop_mcp import resolve_web, special_tools
from pet.config import load_config


class WebMcpTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()

    def test_user_link_and_saved_site_resolve_to_same_address(self):
        address = 'https://www.messenger.com/'
        self.assertEqual(resolve_web(address, self.cfg), (address, 'www.messenger.com'))
        self.assertEqual(resolve_web('Messenger', self.cfg), (address, 'Messenger'))

    def test_invalid_schemes_and_credentials_are_rejected(self):
        for target in ('javascript:alert(1)', 'file:///C:/Windows/System32',
                       'https://user:secret@example.com', 'https://bad site.com'):
            with self.subTest(target=target):
                self.assertIsNone(resolve_web(target, self.cfg))

    def test_open_web_is_exposed_to_bionic(self):
        self.assertIn('OpenWeb', {tool.name for tool in special_tools()})


if __name__ == '__main__':
    unittest.main()
