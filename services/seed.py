"""First-run data seeding — default admin user, optional demo accounts, and
reference categories. Extracted out of app.py so create_app() is just
wiring; called once per boot from inside its app-context block.
"""
import os
from app import db


def seed_defaults():
    """Seed default admin user and reference data on first run."""
    from models.user import User
    from models.product import Category
    from werkzeug.security import generate_password_hash

    if not User.query.filter_by(username='admin').first():
        # ADMIN_PASSWORD lets a production deploy set a real password on first
        # boot instead of inheriting the well-known local-dev default — change
        # it immediately after first login either way.
        admin_password = os.getenv('ADMIN_PASSWORD', 'admin123')
        admin = User(
            username='admin',
            email='admin@vansalesv3.com',
            full_name='System Administrator',
            role='admin',
            is_active=True,
            password_hash=generate_password_hash(admin_password)
        )
        admin.apply_role_defaults()
        db.session.add(admin)

    # Demo accounts are handy for local development but every one of them
    # shares a single well-known password — never auto-create them on a real
    # deployment. Opt in explicitly (e.g. in a local .env) if you want them.
    if os.getenv('SEED_DEMO_USERS', 'false').lower() == 'true':
        demo_users = [
            ('manager1',  'manager@demo.com',   'Demo Manager',          'manager'),
            ('warehouse1','warehouse@demo.com',  'Demo Warehouse Manager','warehouse_manager'),
            ('cashier1',  'cashier@demo.com',    'Demo Cashier',          'cashier'),
            ('rep1',      'rep@demo.com',        'Demo Sales Rep',        'sales_rep'),
            ('supervisor1','super@demo.com',     'Demo Supervisor',       'supervisor'),
        ]
        for uname, email, fname, role in demo_users:
            if not User.query.filter_by(username=uname).first():
                u = User(username=uname, email=email, full_name=fname,
                         role=role, is_active=True,
                         password_hash=generate_password_hash('demo1234'))
                u.apply_role_defaults()
                db.session.add(u)

    default_categories = ['Beverages', 'Snacks', 'Dairy', 'Household', 'Personal Care', 'Other']
    for cat_name in default_categories:
        if not Category.query.filter_by(name=cat_name).first():
            db.session.add(Category(name=cat_name))

    db.session.commit()
