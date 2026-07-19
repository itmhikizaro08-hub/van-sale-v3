from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from models.van import Driver
from datetime import datetime

drivers_bp = Blueprint('drivers', __name__)


@drivers_bp.route('/')
@login_required
def index():
    if not current_user.can_access('drivers'):
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard.index'))
    drivers = Driver.query.order_by(Driver.name).all()
    return render_template('drivers/index.html', drivers=drivers)


@drivers_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not current_user.can_write('drivers'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('drivers.index'))
    if request.method == 'POST':
        license_number = request.form.get('license_number', '').strip() or None
        # Guards against a typo'd duplicate or an accidental double-submit
        # creating two drivers with the same license number.
        if license_number:
            existing = Driver.query.filter(
                db.func.lower(Driver.license_number) == license_number.lower()
            ).first()
            if existing:
                flash(f'A driver with license number "{license_number}" already exists '
                      f'({existing.name}). Edit that record instead.', 'warning')
                return redirect(url_for('drivers.add'))

        expiry = request.form.get('license_expiry')
        driver = Driver(
            name=request.form['name'],
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            license_number=license_number,
            license_expiry=datetime.strptime(expiry, '%Y-%m-%d').date() if expiry else None,
            license_class=request.form.get('license_class'),
            address=request.form.get('address'),
            status=request.form.get('status', 'active'),
            notes=request.form.get('notes')
        )
        db.session.add(driver)
        db.session.commit()
        flash(f'Driver {driver.name} added!', 'success')
        return redirect(url_for('drivers.index'))
    return render_template('drivers/form.html', driver=None)


@drivers_bp.route('/<int:driver_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(driver_id):
    if not current_user.can_write('drivers'):
        flash('Permission denied.', 'danger')
        return redirect(url_for('drivers.index'))
    driver = Driver.query.get_or_404(driver_id)
    if request.method == 'POST':
        license_number = request.form.get('license_number', '').strip() or None
        if license_number:
            existing = Driver.query.filter(
                Driver.id != driver.id,
                db.func.lower(Driver.license_number) == license_number.lower()
            ).first()
            if existing:
                flash(f'A driver with license number "{license_number}" already exists '
                      f'({existing.name}).', 'warning')
                return redirect(url_for('drivers.edit', driver_id=driver.id))

        expiry = request.form.get('license_expiry')
        driver.name = request.form['name']
        driver.phone = request.form.get('phone')
        driver.email = request.form.get('email')
        driver.license_number = license_number
        driver.license_expiry = datetime.strptime(expiry, '%Y-%m-%d').date() if expiry else None
        driver.license_class = request.form.get('license_class')
        driver.address = request.form.get('address')
        driver.status = request.form.get('status', 'active')
        driver.notes = request.form.get('notes')
        db.session.commit()
        flash('Driver updated!', 'success')
        return redirect(url_for('drivers.index'))
    return render_template('drivers/form.html', driver=driver)


@drivers_bp.route('/<int:driver_id>/delete', methods=['POST'])
@login_required
def delete(driver_id):
    if not current_user.can_write('drivers'):
        return jsonify({'error': 'Permission denied'}), 403
    driver = Driver.query.get_or_404(driver_id)
    driver.status = 'inactive'
    db.session.commit()
    return jsonify({'success': True})
