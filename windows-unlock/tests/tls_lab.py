"""Real loopback TLS + the APK's PinnedTls class on host JVM. Not an Android UI test."""
import argparse
from collections import Counter
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from test_unlock import mobile

args=argparse.ArgumentParser(); args.add_argument('--java',required=True); args.add_argument('--classes',required=True); args.add_argument('--offline-only',action='store_true')
opts=args.parse_args()
counts=Counter()
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_POST(self):
        count=int(self.headers.get('Content-Length',0))
        if not 0<=count<=20: return
        self.rfile.read(count) # Public synthetic fixture only; never saved.
        counts[self.path]+=1
        if self.path=='/cut':
            self.close_connection=True
            self.connection.close(); return
        if self.path=='/redirect':
            self.send_response(302); self.send_header('Location','https://127.0.0.1:%d/redirect_target'%self.server.server_port)
            self.send_header('Content-Length','0'); self.end_headers(); return
        if self.path=='/no_reply':
            self.send_response(200); self.send_header('Content-Length','20'); self.end_headers(); self.wfile.flush()
            threading.Event().wait(3); return
        self.send_response(401 if self.path=='/unauthorized' else 200)
        body=b'{"status":"fixture"}'
        self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)

results=[]
with tempfile.TemporaryDirectory(prefix='alex-tls-lab-') as directory:
    cert,key,fp=mobile._certificate(Path(directory))
    other,_,_=mobile._certificate(Path(directory)/'other')
    offline=subprocess.run([opts.java,'-cp',opts.classes,'vn.alex.phone.CertificateLab',str(cert),str(other),fp],capture_output=True,text=True,timeout=12)
    print(offline.stdout.strip())
    if offline.returncode:
        print(offline.stderr[:1800]); raise SystemExit(1)
    if opts.offline_only: raise SystemExit(0)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler); server.daemon_threads=True
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.minimum_version=ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert,key); server.socket=context.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        for mode in ('good','wrong_certificate','redirect','cut','no_reply','unauthorized'):
            start=time.monotonic()
            process=subprocess.run([opts.java,'-cp',opts.classes,'vn.alex.phone.TlsLab',str(server.server_port),fp,mode],capture_output=True,text=True,timeout=12)
            wanted=0 if mode=='wrong_certificate' else 1
            passed=process.returncode==0 and counts['/'+mode]==wanted and not counts['/redirect_target']
            result={'case':mode,'passed':passed,'http_requests':counts['/'+mode],'seconds':round(time.monotonic()-start,2)}
            results.append(result); print(json.dumps(result))
            if process.returncode: print(process.stderr[:1800])
        before=sum(counts.values())
        try:
            with socket.create_connection(('127.0.0.1',server.server_port),timeout=2) as sock:
                sock.sendall(b'POST /plaintext HTTP/1.0\r\nContent-Length: 0\r\n\r\n')
                sock.recv(128)
        except OSError: pass
        results.append({'case':'plaintext_rejected','passed':sum(counts.values())==before})
        print(json.dumps(results[-1]))
    finally: server.shutdown(); server.server_close()
output=Path(__file__).resolve().parents[1]/'build/tls-lab-result.json'
output.write_text(json.dumps(results,indent=2),encoding='utf-8')
raise SystemExit(0 if all(r['passed'] for r in results) else 1)
