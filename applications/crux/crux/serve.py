"""Serve the dashboard for one investigation bundle.

The server binds 127.0.0.1 only. It maps the packaged static/ files to
the site root and the chosen bundle directory to /data/, so the page
can fetch /data/investigation.json without any build step.
"""

from __future__ import annotations

import http.server
import mimetypes
import urllib.parse
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"

_TEXT_TYPES = {
    "text/html",
    "text/css",
    "text/javascript",
    "application/javascript",
    "application/json",
    "text/markdown",
    "text/csv",
    "text/plain",
}


def _resolve(base: Path, relative: str) -> Path | None:
    """Resolve a request path inside base, refusing anything that escapes it."""
    candidate = (base / relative.lstrip("/")).resolve()
    if not candidate.is_relative_to(base.resolve()):
        return None
    if not candidate.is_file():
        return None
    return candidate


def _make_handler(static_dir: Path, data_dir: Path):
    class BundleHandler(http.server.BaseHTTPRequestHandler):
        server_version = "crux"

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            path = urllib.parse.urlparse(self.path).path
            if path in ("", "/"):
                path = "/index.html"
            if path.startswith("/data/"):
                target = _resolve(data_dir, path[len("/data/") :])
            else:
                target = _resolve(static_dir, path)
            if target is None:
                self.send_error(404, "not found")
                return
            body = target.read_bytes()
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype in _TEXT_TYPES:
                ctype += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            # One line per request is plenty; silence would hide 404s.
            print(f"[serve] {self.address_string()} {fmt % args}")

    return BundleHandler


def serve(directory: Path, port: int = 8123) -> None:
    """Serve the dashboard for the bundle in directory until interrupted."""
    directory = Path(directory)
    if not (directory / "investigation.json").exists():
        raise FileNotFoundError(f"no investigation.json in {directory}")
    handler = _make_handler(STATIC_DIR, directory)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"Serving {directory} at http://127.0.0.1:{port}/")
    print("Press ctrl-c to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
