"""Small helper for saving validated image uploads under UPLOAD_FOLDER."""
import os
from datetime import datetime
from flask import current_app
from werkzeug.utils import secure_filename

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
