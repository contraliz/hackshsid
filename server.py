"""Local Flask API and built-frontend server for the GridShift prototype."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory

from backend.data import SCENARIOS
from backend.priority_queue import simulate_request_queue
from backend.dynamic_simulation import run_dynamic_comparison
from backend.scheduler import run_comparison

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "web" / "dist"
app = Flask(__name__)


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "solver": "SciPy linprog / HiGHS", "scenarios": list(SCENARIOS)})


@app.post("/api/schedule")
def schedule():
    payload: Any = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send scenario controls as a JSON object."}), 400
    try:
        return jsonify(run_comparison(payload))
    except ValueError as error:
        return jsonify({"error": str(error)}), 422
    except Exception as error:  # The API reports a useful failure rather than returning stale results.
        app.logger.exception("Scheduling request failed")
        return jsonify({"error": f"The scheduler could not complete this request: {error}"}), 500


@app.post("/api/realtime-queue")
def realtime_queue():
    payload: Any = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send queue controls and requests as a JSON object."}), 400
    try:
        return jsonify(simulate_request_queue(
            payload.get("requests", []),
            scenario=payload.get("scenario", "baseline"),
            gpu_count=payload.get("gpu_count", 256),
            hour=payload.get("hour", 12),
        ))
    except ValueError as error:
        return jsonify({"error": str(error)}), 422
    except Exception as error:
        app.logger.exception("Real-time queue simulation failed")
        return jsonify({"error": f"The queue simulation could not complete: {error}"}), 500


@app.post("/api/dynamic-simulation")
def dynamic_simulation():
    payload: Any = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send simulation controls as a JSON object."}), 400
    try:
        return jsonify(run_dynamic_comparison(payload))
    except ValueError as error:
        return jsonify({"error": str(error)}), 422
    except Exception as error:
        app.logger.exception("Dynamic simulation failed")
        return jsonify({"error": f"The dynamic simulation could not complete: {error}"}), 500


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path: str):
    if not DIST.exists():
        return (
            "GridShift API is running. Start the Vite frontend with `npm run dev`, "
            "or run `npm run build` to serve the production frontend here.",
            200,
            {"Content-Type": "text/plain; charset=utf-8"},
        )
    file_path = (DIST / path).resolve() if path else DIST / "index.html"
    if path and file_path.is_file() and DIST.resolve() in file_path.parents:
        return send_from_directory(DIST, path)
    return send_from_directory(DIST, "index.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False)
