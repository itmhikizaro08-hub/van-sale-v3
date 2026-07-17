"""Small helper for saving validated image uploads under UPLOAD_FOLDER."""
import os
import logging
from datetime import datetime
from flask import current_app
from werkzeug.utils import secure_filename

log = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def save_upload(file_storage, subfolder):
    """Validate and save an uploaded image under UPLOAD_FOLDER/<subfolder>/.
    Returns the relative path (e.g. 'logos/20260101_abc.png') to store in the
    DB, or None if no file / invalid extension."""
    if not file_storage or not file_storage.filename:
        return None

    ext = file_storage.filename.rsplit('.', 1)[-1].lower() if '.' in file_storage.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return None

    filename = secure_filename(file_storage.filename)
    unique_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], subfolder)
    os.makedirs(upload_dir, exist_ok=True)
    file_storage.save(os.path.join(upload_dir, unique_name))
    return f'{subfolder}/{unique_name}'


def regenerate_pwa_icons(logo_abs_path):
    """Re-derive the installed-app icons (180/192/512) from a newly uploaded
    company logo, so installing the PWA shows the real business branding
    instead of the generic placeholder. Best-effort: any failure (corrupt
    image, unsupported mode) just leaves the existing icons in place rather
    than blocking the settings save."""
    try:
        from PIL import Image
        src = Image.open(logo_abs_path).convert('RGBA')

        icons_dir = os.path.join(current_app.static_folder, 'icons')
        os.makedirs(icons_dir, exist_ok=True)

        for size, name in ((180, 'icon-180.png'), (192, 'icon-192.png'), (512, 'icon-512.png')):
            # Letterbox onto a transparent square canvas instead of stretching,
            # so a non-square logo doesn't come out distorted.
            fitted = src.copy()
            fitted.thumbnail((size, size), Image.LANCZOS)
            canvas = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            offset = ((size - fitted.width) // 2, (size - fitted.height) // 2)
            canvas.paste(fitted, offset, fitted)
            canvas.save(os.path.join(icons_dir, name), 'PNG')

        log.info('Regenerated PWA icons from uploaded logo.')
    except Exception as e:
        log.warning(f'PWA icon regeneration skipped: {e}')
