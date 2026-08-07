"""
Simple HTTP server to serve frontend files (HTML, CSS, JS)
Run this in a separate terminal while main.py API server runs on port 8000

Usage:
    python serve_frontend.py
    
Then open: http://localhost:8080
"""
import http.server
import socketserver
import os
import sys
from pathlib import Path

# Windows consoles default to cp1252, which cannot encode the box-drawing
# banner below. Force UTF-8 so startup does not crash with UnicodeEncodeError.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

PORT = 8080
FRONTEND_DIR = os.path.dirname(os.path.abspath(__file__))


class ThreadedHTTPServer(socketserver.ThreadingTCPServer):
    """
    Threaded so a browser's idle keep-alive / speculative preconnect sockets
    cannot block other requests. Plain TCPServer serves one connection at a
    time, which wedges the whole server as soon as a browser holds a socket
    open without sending a request.
    """
    daemon_threads = True     # don't block Ctrl+C on open connections
    allow_reuse_address = True


class FrontendHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=FRONTEND_DIR, **kwargs)
    
    def do_GET(self):
        # Serve index.html for root path
        if self.path == '/':
            self.path = '/index.html'
        
        # Try to find the file
        file_path = os.path.join(FRONTEND_DIR, self.path.lstrip('/'))
        
        if os.path.isfile(file_path):
            return super().do_GET()
        
        # If file doesn't exist and it's not index.html, try index.html
        if not self.path.startswith('/api'):
            self.path = '/index.html'
            file_path = os.path.join(FRONTEND_DIR, self.path.lstrip('/'))
            if os.path.isfile(file_path):
                return super().do_GET()
        
        self.send_error(404, "File not found")
    
    def log_message(self, format, *args):
        # Custom logging (flush so output is visible when redirected to a file)
        print(f"[{self.log_date_time_string()}] {format % args}", flush=True)

if __name__ == "__main__":
    with ThreadedHTTPServer(("", PORT), FrontendHandler) as httpd:
        print(f"""
╔════════════════════════════════════════════════════════════════╗
║           🌐 Frontend Server Started                           ║
╠════════════════════════════════════════════════════════════════╣
║  URL: http://localhost:{PORT}                                  ║
║  Directory: {FRONTEND_DIR}                            ║
║                                                                ║
║  Files being served:                                           ║
║    • index.html (Frontend UI)                                  ║
║    • styles.css (Styling)                                      ║
║    • app.js (JavaScript logic)                                 ║
║                                                                ║
║  API Server: http://localhost:8000                             ║
║  (Make sure main.py is also running!)                          ║
║                                                                ║
║  Press Ctrl+C to stop                                          ║
╚════════════════════════════════════════════════════════════════╝
        """)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n✓ Server stopped")
