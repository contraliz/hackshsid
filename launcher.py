"""Desktop launcher for the portable GridShift Windows build."""

from __future__ import annotations

import ctypes
import threading
import webbrowser
from pathlib import Path
from tkinter import Tk, messagebox, ttk

from werkzeug.serving import make_server

from server import DIST, app


APP_TITLE = "GridShift"


def show_startup_error(message: str) -> None:
    """Show a native message even if Tk cannot initialize."""
    try:
        root = Tk()
        root.withdraw()
        messagebox.showerror(APP_TITLE, message, parent=root)
        root.destroy()
    except Exception:
        ctypes.windll.user32.MessageBoxW(None, message, APP_TITLE, 0x10)


class GridShiftWindow:
    def __init__(self, root: Tk, http_server) -> None:
        self.root = root
        self.http_server = http_server
        self.url = f"http://127.0.0.1:{http_server.server_port}/"
        self.stopping = False
        self.server_thread = threading.Thread(
            target=http_server.serve_forever,
            name="gridshift-local-server",
            daemon=True,
        )
        self.server_thread.start()

        root.title(f"{APP_TITLE} is running")
        root.geometry("460x228")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.stop)

        frame = ttk.Frame(root, padding=(22, 18))
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="GridShift is running locally", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text="The scheduler is available in your browser on this computer.",
            wraplength=410,
        ).pack(anchor="w", pady=(6, 12))

        ttk.Label(frame, text="Local address").pack(anchor="w")
        address = ttk.Entry(frame, state="readonly", width=54)
        address.configure(state="normal")
        address.insert(0, self.url)
        address.configure(state="readonly")
        address.pack(fill="x", pady=(4, 12))
        self.status = ttk.Label(frame, text="Only this computer can connect to this demo.")
        self.status.pack(anchor="w", pady=(0, 12))

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Open GridShift", command=self.open_browser).pack(side="left")
        ttk.Button(buttons, text="Copy address", command=self.copy_address).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Stop and exit", command=self.stop).pack(side="right")

        root.after(350, self.open_browser)
        root.after(800, self.check_server)

    def open_browser(self) -> None:
        try:
            opened = webbrowser.open(self.url, new=2)
            if not opened:
                self.status.configure(text="Browser did not open automatically. Select Open GridShift to try again.")
            else:
                self.status.configure(text="Only this computer can connect to this demo.")
        except Exception as error:
            self.status.configure(text=f"Could not open the browser: {error}. Use Open GridShift to retry.")

    def copy_address(self) -> None:
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.url)
            self.status.configure(text="Local address copied to the clipboard.")
        except Exception as error:
            self.status.configure(text=f"Could not copy the address: {error}")

    def check_server(self) -> None:
        if self.stopping:
            return
        if not self.server_thread.is_alive():
            messagebox.showerror(
                APP_TITLE,
                "The local scheduler stopped unexpectedly. Close this window and launch GridShift again.",
                parent=self.root,
            )
            self.stop()
            return
        self.root.after(1500, self.check_server)

    def stop(self) -> None:
        if self.stopping:
            return
        self.stopping = True
        self.status.configure(text="Stopping the local scheduler…")
        threading.Thread(target=self._stop_server, name="gridshift-shutdown", daemon=True).start()

    def _stop_server(self) -> None:
        try:
            self.http_server.shutdown()
        finally:
            self.http_server.server_close()
            self.server_thread.join(timeout=3)
            self.root.after(0, self.root.destroy)


def main() -> int:
    if not (Path(DIST) / "index.html").is_file():
        show_startup_error(
            "GridShift's bundled web files are missing. Extract or reinstall the complete "
            "GridShift-Windows-x64 folder, then launch GridShift.exe again."
        )
        return 1

    try:
        # Ask Windows for an unused ephemeral port while binding to loopback only.
        http_server = make_server("127.0.0.1", 0, app, threaded=True)
    except OSError as error:
        show_startup_error(
            "GridShift could not start its local web server. Check whether security software "
            f"blocked a local connection, then try again.\n\nDetails: {error}"
        )
        return 1

    try:
        root = Tk()
    except Exception as error:
        http_server.server_close()
        show_startup_error(
            "GridShift could not open its status window. Restart the app; if the problem "
            f"continues, contact the person who shared it.\n\nDetails: {error}"
        )
        return 1

    try:
        GridShiftWindow(root, http_server)
        root.mainloop()
        return 0
    except Exception as error:
        http_server.shutdown()
        http_server.server_close()
        show_startup_error(f"GridShift could not finish starting. Restart the app.\n\nDetails: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
