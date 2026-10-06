import json
import socketserver
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@contextmanager
def servicos_locais(http_status=200):
    requests, emails = [], []

    class HTTPHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            requests.append({"path": self.path, "body": json.loads(body)})
            data = {"ok": http_status == 200, "result": {"message_id": len(requests)}}
            encoded = json.dumps(data).encode()
            self.send_response(http_status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args):
            pass

    class SMTPHandler(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 local.test ESMTP\r\n")
            while line := self.rfile.readline():
                command = line.split(b" ", 1)[0].strip().upper()
                if command in {b"EHLO", b"HELO"}:
                    self.wfile.write(b"250-local.test\r\n250 SIZE 100000\r\n")
                elif command == b"DATA":
                    self.wfile.write(b"354 Send message\r\n")
                    chunks = []
                    while (chunk := self.rfile.readline()) not in {b".\r\n", b""}:
                        chunks.append(chunk[1:] if chunk.startswith(b"..") else chunk)
                    emails.append(b"".join(chunks))
                    self.wfile.write(b"250 Accepted locally\r\n")
                elif command == b"QUIT":
                    self.wfile.write(b"221 Bye\r\n")
                    return
                else:
                    self.wfile.write(b"250 OK\r\n")

    http = ThreadingHTTPServer(("127.0.0.1", 0), HTTPHandler)
    smtp = socketserver.ThreadingTCPServer(("127.0.0.1", 0), SMTPHandler)
    smtp.daemon_threads = True
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (http, smtp)]
    for thread in threads:
        thread.start()
    try:
        yield {"api_base": f"http://127.0.0.1:{http.server_port}", "smtp_port": smtp.server_address[1],
               "requests": requests, "emails": emails}
    finally:
        http.shutdown()
        smtp.shutdown()
        http.server_close()
        smtp.server_close()
        for thread in threads:
            thread.join(timeout=2)
