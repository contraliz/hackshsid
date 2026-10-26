"""Local browser launcher for the GridShift macOS portable package."""

from __future__ import annotations

import threading
import time
import webbrowser
from pathlib import Path

from werkzeug.serving import make_server

from server import DIST, app


def main() -> int:
    if not (Path(DIST) / "index.html").is_file():
        raise SystemExit("GridShift's bundled web files are missing from this package.")

    http_server = make_server("127.0.0.1", 0, app, threaded=True)
    url = f"http://127.0.0.1:{http_server.server_port}/"
    server_thread = threading.Thread(
        target=http_server.serve_forever,
        name="gridshift-local-server",
        daemon=True,
    )
    server_thread.start()

    print("GridShift is running locally.", flush=True)
    print(f"Open this address if the browser did not open: {url}", flush=True)
    print("Keep this Terminal window open. Press Control-C to stop GridShift.", flush=True)
    try:
        if not webbrowser.open(url, new=2):
            print("The browser did not open automatically; use the address above.", flush=True)
        while server_thread.is_alive():
            server_thread.join(timeout=0.5)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nStopping GridShift…", flush=True)
    finally:
        http_server.shutdown()
        http_server.server_close()
        server_thread.join(timeout=3)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
