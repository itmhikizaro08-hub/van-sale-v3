"""Small top-level routes that don't belong to any feature blueprint:
uploaded files, and the two PWA endpoints (service worker + manifest).

Kept as their own blueprint for consistency with every other route group,
instead of being registered directly on the Flask app object inside
create_app(). The 413 (oversized upload) error handler stays registered at
the app level in app.py rather than moving here — Werkzeug can raise it
while dispatching a request to ANY blueprint's view (e.g. a logo upload in
routes/settings.py), and a blueprint-scoped errorhandler only catches
errors raised while handling that blueprint's own routes, so moving it here
would silently stop catching oversized uploads everywhere else.
"""
from flask import Blueprint, current_app, send_from_directory, jsonify

misc_bp = Blueprint('misc', __name__)


@misc_bp.route('/uploads/<path:filename>')
def uploads(filename):
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)


# Served from the root, not /static/sw.js — a service worker's default scope
# is everything at or below the path it's served from, so serving it from
# /static/ would only ever let it control /static/ assets, not the actual
# app pages the manifest's start_url points to.
@misc_bp.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')


# Served dynamically (not a static file) so the name a user sees when
# installing the app reflects their actual configured company name, not a
# hardcoded generic one.
@misc_bp.route('/manifest.json')
def pwa_manifest():
    from models.settings import Settings
    name = Settings.get().company_name or current_app.config['COMPANY_NAME']
    return jsonify({
        'name': name,
        'short_name': name[:20],
        'description': f'{name} — Van Sales ERP',
        'start_url': '/',
        'scope': '/',
        'display': 'standalone',
        'background_color': '#0f172a',
        'theme_color': '#2563EB',
        'orientation': 'any',
        'icons': [
            {'src': '/static/icons/icon-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any maskable'},
            {'src': '/static/icons/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any maskable'}
        ]
    })
