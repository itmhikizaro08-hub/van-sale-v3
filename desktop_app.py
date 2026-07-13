"""
Van Sales V3 — Desktop launcher
================================
Runs the Flask app in a background thread and opens it in its own native
window (no browser address bar/tabs) using pywebview. Closing the window
shuts the whole app down — there is nothing left running afterwards.
"""
import socket
import threading

import webview

from app import create_app


def _free_port():
    """Pick a free localhost port so this never collides with a dev server
    or a previous copy of the app still shutting down."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _run_server(app, port):
    # debug/reloader are dev-server-only features that don't play well
    # running inside a background thread — off for the packaged app.
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False, threaded=True)


def main():
    app = create_app()
    port = _free_port()

    server_thread = threading.Thread(target=_run_server, args=(app, port), daemon=True)
    server_thread.start()

    webview.create_window(
        'Van Sales V3',
        f'http://127.0.0.1:{port}',
        width=1440,
        height=900,
        min_size=(1024, 700),
    )
    webview.start()


if __name__ == '__main__':
    main()
