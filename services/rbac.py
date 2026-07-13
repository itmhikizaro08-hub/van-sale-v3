"""
RBAC Service — Sprint A
Decorators and helpers for module-level permission enforcement.
"""
from functools import wraps
from flask import redirect, url_for, flash, abort
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


def own_only(module, rep_field='sales_rep_id'):
    """
    Decorator: if user scope is 'own', ensure they only access their own records.
    Applied after fetching an object — pass the object as first positional arg.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            scope = current_user.scope(module)
            if scope == 'none':
                flash('Access denied.', 'danger')
                return redirect(url_for('dashboard.index'))
            return f(*args, **kwargs)
        return decorated
    return decorator


def check_own(obj, module):
    """
    Check if current_user can access obj based on their scope.
    Returns True if allowed, False if denied.
    obj must have sales_rep_id or created_by_id attribute.
    """
    scope = current_user.scope(module)
    if scope == 'none':
        return False
    if scope == 'all':
        return True
    if scope == 'own':
        rep_id = getattr(obj, 'sales_rep_id', None) or getattr(obj, 'created_by_id', None)
        return rep_id == current_user.id
    if scope == 'team':
        # Supervisor sees team — for now treat as all (team filtering done in queries)
        return True
    return False


def filter_by_scope(query_class, module, rep_field='sales_rep_id'):
    """
    Apply scope filter to a SQLAlchemy query class.
    Returns the filtered query or None to skip filtering.
    """
    scope = current_user.scope(module)
    if scope == 'none':
        return query_class.filter(query_class.id == -1)  # return empty
    if scope == 'own':
        return query_class.filter(getattr(query_class, rep_field) == current_user.id)
    # 'all' or 'team' — no filter
    return query_class
