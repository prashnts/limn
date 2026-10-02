"""Serve guide/out for previewing, telling the browser not to cache: a rebuild shows on reload.

    uv run python guide/serve.py [port]      # default 4231
"""
import functools
import http.server
import sys
from pathlib import Path


class NoCache(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4231
    handler = functools.partial(NoCache, directory=Path(__file__).parent / 'out')
    http.server.ThreadingHTTPServer(('', port), handler).serve_forever()
