"""
RBAC Service — Sprint A
Decorators and helpers for module-level permission enforcement.
"""
from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user


def require_module(module, need_write=False, need_approve=False):
    """
    Decorator: checks if current_user has access to a module.
    Usage:
        @require_module('loading')           # any read access
        @require_module('sales', need_write=True)
        @require_module('cash_decl', need_approve=True)
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if not current_user.can_access(module):
                flash(f'Access denied — insufficient permissions.', 'danger')
                return redirect(url_for('dashboard.index'))
            if need_write and not current_user.can_write(module):
                flash(f'Write access required for this action.', 'danger')
                return redirect(url_for('dashboard.index'))
            if need_approve and not current_user.can_approve_module(module):
                flash(f'Approval permission required.', 'danger')
                return redirect(url_for('dashboard.index'))
            return f(*args, **kwargs)
        return decorated
    return decorator


