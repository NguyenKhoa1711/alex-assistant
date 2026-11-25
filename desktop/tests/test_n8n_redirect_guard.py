import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pet.external_mcp import _trigger_n8n_webhook


class N8nRedirectGuardTests(unittest.TestCase):
    def test_allowlisted_webhook_redirect_is_not_followed(self):
        hits = []
        class Target(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(True)
                self.send_response(200)
                self.end_headers()
            def log_message(self,*args): pass
        target = ThreadingHTTPServer(('127.0.0.1',0),Target)
        class Redirect(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(302)
                self.send_header('Location', f'http://127.0.0.1:{target.server_port}/target')
                self.end_headers()
            def log_message(self,*args): pass
        origin = ThreadingHTTPServer(('127.0.0.1',0),Redirect)
        for srv in (target,origin):
            threading.Thread(target=srv.serve_forever,daemon=True).start()
        try:
            cfg={'computer':{'n8n_mcp':{'enabled':True,'webhook_base':
                 f'http://127.0.0.1:{origin.server_port}/webhook','allowed_webhooks':['test']}}}
            result = _trigger_n8n_webhook('test',{},cfg)
            self.assertFalse(result['ok'])
            self.assertEqual(hits,[])
        finally:
            for srv in (origin,target):
                srv.shutdown()
                srv.server_close()


if __name__ == '__main__':
    unittest.main()
