from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from datetime import datetime
from app import db
from models.user import User
from services.uploads import save_upload

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember_me') == 'on'

        user = User.query.filter(
            (User.username == username) | (User.email == username)
        ).first()

        if user and user.check_password(password):
            if not user.is_active:
                flash('Your account is inactive. Contact administrator.', 'danger')
                return render_template('auth/login.html')
            login_user(user, remember=remember)
            user.last_login = datetime.utcnow()
            db.session.commit()
            next_page = request.args.get('next')
            flash(f'Welcome back, {user.full_name}!', 'success')
            return redirect(next_page or url_for('dashboard.index'))
        else:
            flash('Invalid username or password.', 'danger')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_pass = request.form.get('current_password')
        new_pass = request.form.get('new_password')
        confirm_pass = request.form.get('confirm_password')

        if not current_user.check_password(current_pass):
            flash('Current password is incorrect.', 'danger')
        elif new_pass != confirm_pass:
            flash('New passwords do not match.', 'danger')
        elif len(new_pass) < 6:
            flash('Password must be at least 6 characters.', 'danger')
        else:
            current_user.set_password(new_pass)
            db.session.commit()
            flash('Password changed successfully!', 'success')
            return redirect(url_for('dashboard.index'))

    return render_template('auth/change_password.html')


@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.full_name = request.form.get('full_name', current_user.full_name)
        current_user.phone = request.form.get('phone', current_user.phone)
        current_user.email = request.form.get('email', current_user.email)
        current_user.theme_preference = request.form.get('theme_preference', current_user.theme_preference)

        avatar_file = request.files.get('avatar')
        if avatar_file and avatar_file.filename:
            avatar_path = save_upload(avatar_file, 'avatars')
            if avatar_path:
                current_user.avatar = avatar_path
            else:
                flash('Photo not updated — use a PNG, JPG, GIF, or WEBP image.', 'warning')

        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('auth.profile'))
    return render_template('auth/profile.html')


# ── User Management (Admin only) ───────────────────────────────────────────────
@auth_bp.route('/users')
@login_required
def users():
    if not current_user.is_admin:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    users = User.query.order_by(User.full_name).all()
    return render_template('auth/users.html', users=users)


@auth_bp.route('/users/add', methods=['GET', 'POST'])
@login_required
def add_user():
    if not current_user.is_manager:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        full_name = request.form.get('full_name', '').strip()
        role = request.form.get('role', 'sales_rep')
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')

        valid_roles = {'admin', 'manager', 'supervisor', 'sales_rep', 'warehouse_manager', 'cashier'}
        if role not in valid_roles:
            flash('Invalid role selected.', 'danger')
            return render_template('auth/add_user.html')

        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('Email already exists.', 'danger')
        else:
            user = User(
                username=username, email=email,
                full_name=full_name, role=role, phone=phone
            )
            user.set_password(password)
            user.apply_role_defaults()
            db.session.add(user)
            db.session.commit()
            flash(f'User {full_name} created successfully!', 'success')
            return redirect(url_for('auth.users'))

    return render_template('auth/add_user.html')


@auth_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@login_required
def toggle_user(user_id):
    if not current_user.is_admin:
        return {'error': 'Access denied'}, 403
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        return {'error': 'Cannot deactivate yourself'}, 400
    user.is_active = not user.is_active
    db.session.commit()
    return {'success': True, 'is_active': user.is_active}
