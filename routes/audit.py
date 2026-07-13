"""Pricing Audit Trail — admin-only view of every pricing decision made at sale time."""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from models.audit import PricingAuditLog
from models.user import User

audit_bp = Blueprint('audit', __name__)


@audit_bp.route('/')
@login_required
def index():
    if not current_user.can_access('audit'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    start  = request.args.get('start', (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end    = request.args.get('end',   datetime.utcnow().strftime('%Y-%m-%d'))
    rep_id = request.args.get('rep_id', type=int)

    q = PricingAuditLog.query.filter(
        PricingAuditLog.created_at >= start,
        PricingAuditLog.created_at <= end + ' 23:59:59'
    )
    if rep_id:
        q = q.filter(PricingAuditLog.user_id == rep_id)

    logs = q.order_by(PricingAuditLog.created_at.desc()).limit(500).all()
    reps = User.query.filter(User.role == 'sales_rep', User.is_active == True).order_by(User.full_name).all()

    return render_template('audit/index.html', logs=logs, reps=reps,
                            start=start, end=end, sel_rep=rep_id)
