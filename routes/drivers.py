from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from models.van import Driver
from datetime import datetime

drivers_bp = Blueprint('drivers', __name__)


@drivers_bp.route('/')
@login_required
def index():
    drivers = Driver.query.order_by(Driver.name).all()
    return render_template('drivers/index.html', drivers=drivers)


@drivers_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if request.method == 'POST':
        expiry = request.form.get('license_expiry')
        driver = Driver(
            name=request.form['name'],
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            license_number=request.form.get('license_number'),
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
    driver = Driver.query.get_or_404(driver_id)
    if request.method == 'POST':
        expiry = request.form.get('license_expiry')
        driver.name = request.form['name']
        driver.phone = request.form.get('phone')
        driver.email = request.form.get('email')
        driver.license_number = request.form.get('license_number')
        driver.license_expiry = datetime.strptime(expiry, '%Y-%m-%d').date() if expiry else None
        driver.license_class = request.form.get('license_class')
        driver.address = request.form.get('address')
        driver.status = request.form.get('status', 'active')
        driver.notes = request.form.get('notes')
        db.session.commit()
        flash('Driver updated!', 'success')
        return redirect(url_for('drivers.index'))
    return render_template('drivers/form.html', driver=driver)
