"""
Van Sales V3 ERP System
Main Application Entry Point
"""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from dotenv import load_dotenv
import os

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()


def create_app():
    app = Flask(__name__)

    # ── Configuration ──────────────────────────────────────────────────────────
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-change-me')
    # Render/Heroku-style hosts hand out "postgres://" URLs, but SQLAlchemy 1.4+
    # only recognizes "postgresql://" — rewrite it rather than fail at connect time.
    db_url = os.getenv('DATABASE_URL', 'sqlite:///van_sales_v3.db')
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'uploads')
    app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))

    # Company info available to all templates
    app.config['COMPANY_NAME'] = os.getenv('COMPANY_NAME', 'Van Sales V3 ERP')
    app.config['COMPANY_PHONE'] = os.getenv('COMPANY_PHONE', '+233 XX XXX XXXX')
    app.config['COMPANY_EMAIL'] = os.getenv('COMPANY_EMAIL', 'info@vansalesv3.com')
    app.config['COMPANY_ADDRESS'] = os.getenv('COMPANY_ADDRESS', 'Accra, Ghana')

    # ── Extensions ─────────────────────────────────────────────────────────────
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'warning'

    # ── Register Blueprints ────────────────────────────────────────────────────
    from routes.auth import auth_bp
    from routes.dashboard import dashboard_bp
    from routes.customers import customers_bp
    from routes.products import products_bp
    from routes.inventory import inventory_bp
    from routes.sales import sales_bp
    from routes.invoices import invoices_bp
    from routes.payments import payments_bp
    from routes.returns import returns_bp
    from routes.vans import vans_bp
    from routes.drivers import drivers_bp
    from routes.route_management import routes_bp
    from routes.visits import visits_bp
    from routes.suppliers import suppliers_bp
    from routes.expenses import expenses_bp
    from routes.sms import sms_bp
    from routes.reports import reports_bp
    from routes.notifications import notifications_bp
    from routes.api import api_bp
    from routes.notes import notes_bp
    from routes.tips import tips_bp
    from routes.cash_decl import cash_decl_bp
    from routes.audit import audit_bp
    from routes.pricing import pricing_bp
    from routes.settings import settings_bp
    from routes.insights import insights_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(dashboard_bp, url_prefix='/')
    app.register_blueprint(customers_bp, url_prefix='/customers')
    app.register_blueprint(products_bp, url_prefix='/products')
    app.register_blueprint(inventory_bp, url_prefix='/inventory')
    app.register_blueprint(sales_bp, url_prefix='/sales')
    app.register_blueprint(invoices_bp, url_prefix='/invoices')
    app.register_blueprint(payments_bp, url_prefix='/payments')
    app.register_blueprint(returns_bp, url_prefix='/returns')
    app.register_blueprint(vans_bp, url_prefix='/vans')
    app.register_blueprint(drivers_bp, url_prefix='/drivers')
    app.register_blueprint(routes_bp, url_prefix='/routes')
    app.register_blueprint(visits_bp, url_prefix='/visits')
    app.register_blueprint(suppliers_bp, url_prefix='/suppliers')
    app.register_blueprint(expenses_bp, url_prefix='/expenses')
    app.register_blueprint(sms_bp, url_prefix='/sms')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(notifications_bp, url_prefix='/notifications')
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(notes_bp, url_prefix='/notes')
    app.register_blueprint(tips_bp, url_prefix='/tips')
    app.register_blueprint(cash_decl_bp, url_prefix='/cash-decl')
    app.register_blueprint(audit_bp, url_prefix='/audit')
    app.register_blueprint(pricing_bp, url_prefix='/pricing')
    app.register_blueprint(settings_bp, url_prefix='/settings')
    app.register_blueprint(insights_bp, url_prefix='/insights')

    # ── Uploaded files (logos, avatars) ────────────────────────────────────────
    @app.route('/uploads/<path:filename>')
    def uploads(filename):
        from flask import send_from_directory
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    # ── PWA service worker ─────────────────────────────────────────────────────
    # Served from the root, not /static/sw.js — a service worker's default
    # scope is everything at or below the path it's served from, so serving it
    # from /static/ would only ever let it control /static/ assets, not the
    # actual app pages the manifest's start_url points to.
    @app.route('/sw.js')
    def service_worker():
        from flask import send_from_directory
        return send_from_directory('static', 'sw.js', mimetype='application/javascript')

    # ── Friendly error for oversized uploads ───────────────────────────────────
    @app.errorhandler(413)
    def handle_large_upload(e):
        from flask import redirect, request, flash, url_for
        max_mb = app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
        flash(f'File is too large. Maximum upload size is {max_mb}MB.', 'danger')
        return redirect(request.referrer or url_for('dashboard.index'))

    # ── Template filters ────────────────────────────────────────────────────────
    @app.template_filter('qty')
    def format_qty(value):
        """Render a quantity without a spurious '.0' now that stock/sale
        quantities are floats (to support selling by the piece) — whole
        numbers still display as whole numbers, fractional ones keep up to
        2 decimal places."""
        if value is None:
            return '0'
        v = float(value)
        if v == int(v):
            return str(int(v))
        return f'{v:.2f}'.rstrip('0').rstrip('.')

    # ── Context processors ─────────────────────────────────────────────────────
    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        from models.notification import Notification, NotificationRead
        from models.settings import Settings
        unread_count = 0
        if current_user.is_authenticated and current_user.can_access('notifications'):
            read_ids = {r.notification_id for r in
                        NotificationRead.query.filter_by(user_id=current_user.id).all()}
            total_ids = {n.id for n in Notification.query.with_entities(Notification.id).all()}
            unread_count = len(total_ids - read_ids)
        settings = Settings.get()
        return dict(
            company_name=settings.company_name or app.config['COMPANY_NAME'],
            company_logo=settings.company_logo,
            unread_notifications=unread_count
        )

    # ── Create DB tables ───────────────────────────────────────────────────────
    with app.app_context():
        from models import v4_models  # noqa - registers V4 tables
        # Run migrations first (handles existing DBs without breaking them)
        from services.migrate import run_migrations
        run_migrations(db)
        # Create any brand-new tables
        db.create_all()
        _seed_defaults()

        from models.user import load_role_permissions
        load_role_permissions()

        os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'logos'), exist_ok=True)
        os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'avatars'), exist_ok=True)

    from datetime import datetime
    @app.context_processor
    def inject_now():
        return {'now': datetime.utcnow()}

    return app


def _seed_defaults():
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


# ── User loader ────────────────────────────────────────────────────────────────
@login_manager.user_loader
def load_user(user_id):
    from models.user import User
    return User.query.get(int(user_id))


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
