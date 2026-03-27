"""Railway service entrypoint for web and worker roles.

Railway config-as-code applies one start command project-wide, so we dispatch
between the web app and the Specter worker using an environment variable.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import runpy
import threading

from agent.runtime_env import validate_runtime_environment


class _WorkerHealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok\n")
            return
        self.send_response(404)
        self.end_headers()

    def do_HEAD(self) -> None:  # noqa: N802
        if self.path == "/":
            self.send_response(200)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def _start_worker_health_server() -> ThreadingHTTPServer:
    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), _WorkerHealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Specter worker health server listening on 0.0.0.0:{port}")
    return server


def main() -> int:
    role = os.getenv("SERVICE_ROLE", "web").strip().lower()
    validate_runtime_environment(service_role=role)
    if role == "worker":
        from agent import specter_batch_worker

        server = _start_worker_health_server()
        try:
            return specter_batch_worker.main()
        finally:
            server.shutdown()
            server.server_close()

    runpy.run_module("web.app", run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
