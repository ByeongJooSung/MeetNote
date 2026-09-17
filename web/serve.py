#!/usr/bin/env python3
"""로컬 테스트 서버. 실행: python3 serve.py  →  http://localhost:8080
같은 와이파이의 휴대폰에서 마이크까지 쓰려면 HTTPS가 필요합니다. README의 '휴대폰에서 테스트' 참고."""
import http.server, socketserver, os, mimetypes
mimetypes.add_type('application/manifest+json', '.webmanifest')
mimetypes.add_type('application/x-mnote+zip', '.mnote')
os.chdir(os.path.dirname(os.path.abspath(__file__)))
class H(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()
PORT = int(os.environ.get('PORT', 8080))
with socketserver.TCPServer(('0.0.0.0', PORT), H) as s:
    print(f'MeetNote: http://localhost:{PORT}  (Ctrl+C로 종료)')
    s.serve_forever()
