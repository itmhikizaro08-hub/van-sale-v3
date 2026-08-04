"""Lightweight in-app error log.

Captures unhandled exceptions so an admin without hosting-platform log
access (see app.py's teardown_request hook) can still see what broke and
why, straight from inside the app itself.
"""
from app import db
from datetime import datetime


class ErrorLog(db.Model):
    __tablename__ = 'error_logs'

    id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.String(255))
    method = db.Column(db.String(10))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    error_type = db.Column(db.String(255))
    error_message = db.Column(db.Text)
    traceback_text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id])
