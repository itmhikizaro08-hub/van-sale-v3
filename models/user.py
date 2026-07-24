from app import db, login_manager
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash


# ── Module-level permission matrix ────────────────────────────────────────────
# Format: role -> module -> ('none'|'own'|'team'|'all', can_write, can_approve)
ROLE_PERMISSIONS = {
    'admin': {
        'dashboard':     ('all',  True,  True),
        'sales':         ('all',  True,  True),
        'invoices':      ('all',  True,  True),
        'payments':      ('all',  True,  True),
        'customers':     ('all',  True,  True),
        'products':      ('all',  True,  True),
        'inventory':     ('all',  True,  True),
        'loading':       ('all',  True,  True),
        'van_stock':     ('all',  True,  True),
        'routes':        ('all',  True,  True),
        'returns':       ('all',  True,  True),
        'notes':         ('all',  True,  True),
        'suppliers':     ('all',  True,  True),
        'procurement':   ('all',  True,  True),
        'expenses':      ('all',  True,  True),
        'reports':       ('all',  True,  True),
        'tips':          ('all',  True,  True),
        'cash_decl':     ('all',  True,  True),
        'stock_offload': ('all',  True,  True),
        'gps_map':       ('all',  False, False),
        'visits':        ('all',  True,  True),
        'audit':         ('all',  False, False),
        'settings':      ('all',  True,  True),
        'users':         ('all',  True,  True),
        'cost_prices':   ('all',  False, False),
        'notifications': ('all',  True,  True),
        'vans':          ('all',  True,  False),
        'drivers':       ('all',  True,  False),
        'sms':           ('all',  True,  True),
        'insights':      ('all',  False, False),
    },
    'manager': {
        'dashboard':     ('all',  False, True),
        'sales':         ('all',  True,  True),
        'invoices':      ('all',  True,  False),
        'payments':      ('all',  True,  True),
        'customers':     ('all',  True,  False),
        'products':      ('all',  True,  False),
        'inventory':     ('all',  False, True),
        'loading':       ('all',  False, False),
        'van_stock':     ('all',  False, False),
        'routes':        ('all',  True,  False),
        'returns':       ('all',  False, True),
        'notes':         ('all',  True,  False),
        'suppliers':     ('all',  True,  True),   # approve cashier payment proposals
        'procurement':   ('all',  True,  True),
        'expenses':      ('all',  False, True),
        'reports':       ('all',  False, False),
        'tips':          ('all',  False, False),   # view all tips, read-only (see routes/tips.py)
        'cash_decl':     ('all',  False, True),
        'stock_offload': ('all',  False, True),
        'gps_map':       ('all',  False, False),
        'visits':        ('all',  False, False),
        'audit':         ('none', False, False),
        'settings':      ('none', False, False),
        'users':         ('none', False, False),
        'cost_prices':   ('all',  False, False),
        'notifications': ('all',  True,  True),
        'vans':          ('all',  True,  False),
        'drivers':       ('all',  True,  False),
        'sms':           ('all',  True,  False),
        'insights':      ('all',  False, False),
    },
    'supervisor': {
        'dashboard':     ('team', False, False),
        'sales':         ('team', False, False),
        'invoices':      ('team', False, False),
        'payments':      ('none', False, False),
        'customers':     ('all',  True,  False),
        'products':      ('all',  False, False),
        'inventory':     ('all',  False, False),
        'loading':       ('all',  False, False),
        'van_stock':     ('all',  False, False),
        'routes':        ('all',  False, False),
        'returns':       ('none', False, False),
        'notes':         ('none', False, False),
        'suppliers':     ('none', False, False),
        'procurement':   ('none', False, False),
        'expenses':      ('team', False, False),
        'reports':       ('team', False, False),
        'tips':          ('none', False, False),
        'cash_decl':     ('none', False, False),
        'stock_offload': ('none', False, False),
        'gps_map':       ('all',  False, False),
        'visits':        ('all',  False, False),
        'audit':         ('none', False, False),
        'settings':      ('none', False, False),
        'users':         ('none', False, False),
        'cost_prices':   ('all',  False, False),
        'notifications': ('all',  False, False),
        'vans':          ('all',  False, False),
        'drivers':       ('all',  False, False),
        'sms':           ('none', False, False),
        'insights':      ('none', False, False),
    },
    'sales_rep': {
        'dashboard':     ('own',  False, False),
        'sales':         ('own',  True,  False),
        'invoices':      ('own',  False, False),
        'payments':      ('own',  True,  False),
        'customers':     ('own',  True,  False),   # own route only
        'products':      ('all',  False, False),   # no cost prices
        'inventory':     ('none', False, False),
        'loading':       ('own',  False, False),   # view own only
        'van_stock':     ('own',  False, False),   # own van only
        'routes':        ('none', False, False),
        'returns':       ('own',  True,  False),   # submit only
        'notes':         ('none', False, False),
        'suppliers':     ('none', False, False),
        'procurement':   ('none', False, False),
        'expenses':      ('own',  True,  False),   # submit own
        'reports':       ('own',  False, False),   # own performance
        'tips':          ('own',  False, False),   # own tips only, read-only (see routes/tips.py)
        'cash_decl':     ('own',  True,  False),   # submit own
        'stock_offload': ('own',  True,  False),   # submit own
        'gps_map':       ('own',  False, False),   # own route only ← FIXED
        'visits':        ('own',  True,  False),
        'audit':         ('none', False, False),
        'settings':      ('none', False, False),
        'users':         ('none', False, False),
        'cost_prices':   ('none', False, False),   # HIDDEN
        'notifications': ('none', False, False),   # no operational relevance
        'vans':          ('none', False, False),   # Fleet section hidden from reps
        'drivers':       ('none', False, False),
        'sms':           ('none', False, False),
        'insights':      ('none', False, False),
    },
    'warehouse_manager': {
        'dashboard':     ('all',  False, False),
        'sales':         ('none', False, False),
        'invoices':      ('none', False, False),
        'payments':      ('none', False, False),
        'customers':     ('none', False, False),
        'products':      ('all',  True,  False),
        'inventory':     ('all',  True,  True),
        'loading':       ('all',  True,  False),   # create loading sheets
        'van_stock':     ('all',  False, False),
        'routes':        ('none', False, False),
        'returns':       ('all',  True,  False),   # receive returns
        'notes':         ('none', False, False),
        'suppliers':     ('all',  False, False),   # view only
        'procurement':   ('all',  True,  False),   # submit supplier returns
        'expenses':      ('none', False, False),
        'reports':       ('all',  False, False),   # stock reports only
        'tips':          ('none', False, False),
        'cash_decl':     ('none', False, False),
        'stock_offload': ('all',  True,  True),    # receive & confirm
        'gps_map':       ('none', False, False),
        'visits':        ('none', False, False),
        'audit':         ('none', False, False),
        'settings':      ('none', False, False),
        'users':         ('none', False, False),
        'cost_prices':   ('all',  False, False),
        'notifications': ('all',  True,  False),   # low-stock alerts relevant to them
        'vans':          ('all',  False, False),   # loads vans, doesn't manage the fleet
        'drivers':       ('all',  False, False),
        'sms':           ('none', False, False),
        'insights':      ('none', False, False),
    },
    'cashier': {
        'dashboard':     ('all',  False, False),
        'sales':         ('all',  False, False),   # view only
        'invoices':      ('all',  False, False),
        'payments':      ('all',  True,  True),
        'customers':     ('none', False, False),
        'products':      ('none', False, False),
        'inventory':     ('none', False, False),
        'loading':       ('none', False, False),
        'van_stock':     ('none', False, False),
        'routes':        ('none', False, False),
        'returns':       ('none', False, False),
        'notes':         ('all',  False, False),   # view only
        'suppliers':     ('all',  True,  False),   # propose payments, needs manager/admin approval
        'procurement':   ('none', False, False),
        'expenses':      ('none', False, False),
        'reports':       ('all',  False, False),   # cash reports only
        'tips':          ('none', False, False),
        'cash_decl':     ('all',  True,  True),    # verify declarations
        'stock_offload': ('none', False, False),
        'gps_map':       ('none', False, False),
        'visits':        ('none', False, False),
        'audit':         ('none', False, False),
        'settings':      ('none', False, False),
        'users':         ('none', False, False),
        'cost_prices':   ('none', False, False),
        'notifications': ('all',  True,  False),   # outstanding-balance alerts relevant to them
        'vans':          ('none', False, False),
        'drivers':       ('none', False, False),
        'sms':           ('none', False, False),
        'insights':      ('none', False, False),
    },
}

# Max discount per role
DISCOUNT_LIMITS = {
    'admin':            100,
    'manager':          100,
    'supervisor':       15,
    'sales_rep':        5,
    'warehouse_manager':0,
    'cashier':          0,
}


class RolePermission(db.Model):
    """DB-backed override store for ROLE_PERMISSIONS, editable from Settings."""
    __tablename__ = 'role_permissions'

    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(30), nullable=False)
    module = db.Column(db.String(30), nullable=False)
    scope = db.Column(db.String(10), default='none')
    can_write = db.Column(db.Boolean, default=False)
    can_approve = db.Column(db.Boolean, default=False)

    __table_args__ = (db.UniqueConstraint('role', 'module', name='uq_role_module'),)


def load_role_permissions():
    """Seed RolePermission from the hardcoded matrix on first run, then load DB
    rows into ROLE_PERMISSIONS in place so every User.perm() lookup reflects
    admin edits immediately — no caching layer to invalidate."""
    if RolePermission.query.count() == 0:
        for role, modules in ROLE_PERMISSIONS.items():
            for module, (scope, write, approve) in modules.items():
                db.session.add(RolePermission(role=role, module=module, scope=scope,
                                               can_write=write, can_approve=approve))
        db.session.commit()

    for row in RolePermission.query.all():
        ROLE_PERMISSIONS.setdefault(row.role, {})[row.module] = (row.scope, row.can_write, row.can_approve)


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(20))
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(30), nullable=False, default='sales_rep')
    # roles: admin, manager, supervisor, sales_rep, warehouse_manager, cashier
    is_active = db.Column(db.Boolean, default=True)
    avatar = db.Column(db.String(255))
    theme_preference = db.Column(db.String(10), default='light')
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Legacy per-user overrides (can still be set manually)
    can_view   = db.Column(db.Boolean, default=True)
    can_add    = db.Column(db.Boolean, default=False)
    can_edit   = db.Column(db.Boolean, default=False)
    can_delete = db.Column(db.Boolean, default=False)
    can_approve= db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # ── RBAC helpers ──────────────────────────────────────────────────────────

    def perm(self, module):
        """Return (scope, can_write, can_approve) for this user's role on a module."""
        role_perms = ROLE_PERMISSIONS.get(self.role, {})
        return role_perms.get(module, ('none', False, False))

    def can_access(self, module):
        """True if user has any access to this module."""
        scope, _, _ = self.perm(module)
        return scope != 'none'

    def can_write(self, module):
        """True if user can create/edit in this module."""
        _, write, _ = self.perm(module)
        return write

    def can_approve_module(self, module):
        """True if user can approve actions in this module."""
        _, _, approve = self.perm(module)
        return approve

    def scope(self, module):
        """Return data scope: 'none'|'own'|'team'|'all'."""
        s, _, _ = self.perm(module)
        return s

    def max_discount(self):
        return DISCOUNT_LIMITS.get(self.role, 0)

    def see_cost_prices(self):
        scope, _, _ = self.perm('cost_prices')
        return scope != 'none'

    # ── Role shortcuts ────────────────────────────────────────────────────────

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_manager(self):
        return self.role in ('admin', 'manager')

    @property
    def is_warehouse(self):
        return self.role == 'warehouse_manager'

    @property
    def is_cashier(self):
        return self.role == 'cashier'

    @property
    def is_rep(self):
        return self.role == 'sales_rep'

    @property
    def role_label(self):
        return {
            'admin':             'Administrator',
            'manager':           'Manager',
            'supervisor':        'Supervisor',
            'sales_rep':         'Sales Representative',
            'warehouse_manager': 'Warehouse Manager',
            'cashier':           'Cashier',
        }.get(self.role, self.role.replace('_', ' ').title())

    @property
    def role_badge_class(self):
        return {
            'admin':             'bg-danger',
            'manager':           'bg-primary',
            'supervisor':        'bg-warning text-dark',
            'sales_rep':         'bg-success',
            'warehouse_manager': 'bg-info text-dark',
            'cashier':           'bg-secondary',
        }.get(self.role, 'bg-secondary')

    @property
    def dashboard_template(self):
        """Which dashboard template to render for this role."""
        return {
            'admin':             'dashboard/admin.html',
            'manager':           'dashboard/manager.html',
            'supervisor':        'dashboard/supervisor.html',
            'sales_rep':         'dashboard/rep.html',
            'warehouse_manager': 'dashboard/warehouse.html',
            'cashier':           'dashboard/cashier.html',
        }.get(self.role, 'dashboard/index.html')

    def apply_role_defaults(self):
        """Set legacy boolean permissions based on role."""
        defaults = {
            'admin':             (True, True,  True,  True,  True),
            'manager':           (True, True,  True,  False, True),
            'supervisor':        (True, True,  True,  False, False),
            'sales_rep':         (True, True,  False, False, False),
            'warehouse_manager': (True, True,  True,  False, True),
            'cashier':           (True, True,  False, False, True),
        }
        v, a, e, d, ap = defaults.get(self.role, (True, False, False, False, False))
        self.can_view    = v
        self.can_add     = a
        self.can_edit    = e
        self.can_delete  = d
        self.can_approve = ap

    def sidebar_items(self):
        """Return sidebar nav items this user can see, grouped by section."""
        sections = []

        # ── SALES ────────────────────────────────────────────────────────
        sales_items = []
        if self.can_access('sales'):
            sales_items.append({'label': 'Quick Sale', 'icon': 'fas fa-bolt',
                                 'url': 'sales.new_sale', 'bp': 'sales', 'endpoint': 'sales.new_sale'})
            sales_items.append({'label': 'All Sales', 'icon': 'fas fa-shopping-cart',
                                 'url': 'sales.index', 'bp': 'sales', 'endpoint': 'sales.index'})
        if self.can_access('invoices'):
            sales_items.append({'label': 'Invoices', 'icon': 'fas fa-file-invoice',
                                 'url': 'invoices.index', 'bp': 'invoices'})
        if self.can_access('payments'):
            sales_items.append({'label': 'Payments', 'icon': 'fas fa-money-bill-wave',
                                 'url': 'payments.index', 'bp': 'payments'})
        if self.can_access('returns'):
            sales_items.append({'label': 'Returns', 'icon': 'fas fa-undo-alt',
                                 'url': 'returns.index', 'bp': 'returns',
                                 'match_endpoints': ['returns.index', 'returns.new', 'returns.view']})
        if self.can_access('notes') and self.role in ('admin', 'manager'):
            sales_items.append({'label': 'Credit/Debit Notes', 'icon': 'fas fa-receipt',
                                 'url': 'notes.index', 'bp': 'notes'})
        if self.can_access('tips'):
            if self.scope('tips') == 'own':
                sales_items.append({'label': 'My Tips', 'icon': 'fas fa-coins',
                                     'url': 'tips.my_tips', 'bp': 'tips'})
            elif self.scope('tips') == 'all':
                sales_items.append({'label': 'Tips Report', 'icon': 'fas fa-coins',
                                     'url': 'tips.report', 'bp': 'tips'})
        if sales_items:
            sections.append({'label': 'Sales', 'icon': 'fas fa-shopping-cart', 'items': sales_items})

        # ── CUSTOMERS ────────────────────────────────────────────────────
        crm_items = []
        if self.can_access('customers'):
            crm_items.append({'label': 'Customers', 'icon': 'fas fa-users',
                               'url': 'customers.index', 'bp': 'customers'})
        if self.can_access('visits'):
            crm_items.append({'label': 'Visits', 'icon': 'fas fa-map-pin',
                               'url': 'visits.index', 'bp': 'visits'})
        if self.can_access('sms'):
            crm_items.append({'label': 'SMS Center', 'icon': 'fas fa-sms',
                               'url': 'sms.index', 'bp': 'sms'})
        if crm_items:
            sections.append({'label': 'Customers', 'icon': 'fas fa-users', 'items': crm_items})

        # ── STOCK ────────────────────────────────────────────────────────
        stock_items = []
        if self.can_access('products'):
            stock_items.append({'label': 'Products', 'icon': 'fas fa-box',
                                 'url': 'products.index', 'bp': 'products'})
        if self.role in ('admin', 'manager') and self.can_write('products'):
            stock_items.append({'label': 'Pricing Management', 'icon': 'fas fa-tags',
                                 'url': 'pricing.index', 'bp': 'pricing'})
        if self.can_access('inventory'):
            stock_items.append({'label': 'Inventory', 'icon': 'fas fa-warehouse',
                                 'url': 'inventory.index', 'bp': 'inventory'})
        if self.can_access('loading'):
            stock_items.append({'label': 'Loading Sheets', 'icon': 'fas fa-clipboard-list',
                                 'url': 'vans.loading_index', 'bp': 'vans',
                                 'match_endpoints': ['vans.loading_index', 'vans.loading_new', 'vans.loading_view']})
        if self.can_access('van_stock'):
            stock_items.append({'label': 'Van Stock', 'icon': 'fas fa-truck-loading',
                                 'url': 'vans.stock', 'bp': 'vans',
                                 'match_endpoints': ['vans.stock']})
        if self.can_access('stock_offload'):
            stock_items.append({'label': 'Stock Offload', 'icon': 'fas fa-dolly',
                                 'url': 'vans.offload_index', 'bp': 'vans',
                                 'match_endpoints': ['vans.offload_index', 'vans.offload_submit', 'vans.offload_confirm']})
        if stock_items:
            sections.append({'label': 'Stock', 'icon': 'fas fa-boxes', 'items': stock_items})

        # ── FLEET ────────────────────────────────────────────────────────
        fleet_items = []
        if self.can_access('vans'):
            fleet_items.append({'label': 'Vans', 'icon': 'fas fa-truck',
                                 'url': 'vans.index', 'bp': 'vans',
                                 'match_endpoints': ['vans.index', 'vans.add', 'vans.view', 'vans.edit']})
        if self.can_access('drivers'):
            fleet_items.append({'label': 'Drivers', 'icon': 'fas fa-id-badge',
                                 'url': 'drivers.index', 'bp': 'drivers'})
        if self.can_access('routes'):
            fleet_items.append({'label': 'Routes', 'icon': 'fas fa-route',
                                 'url': 'routes.index', 'bp': 'routes'})
        if fleet_items:
            sections.append({'label': 'Fleet', 'icon': 'fas fa-truck', 'items': fleet_items})

        # ── MONEY ────────────────────────────────────────────────────────
        money_items = []
        if self.can_access('suppliers'):
            money_items.append({'label': 'Suppliers', 'icon': 'fas fa-industry',
                                 'url': 'suppliers.index', 'bp': 'suppliers'})
        if self.can_access('procurement'):
            money_items.append({'label': 'Supplier Returns', 'icon': 'fas fa-truck-ramp-box',
                                 'url': 'returns.supplier_index', 'bp': 'returns',
                                 'match_endpoints': ['returns.supplier_index', 'returns.supplier_new', 'returns.supplier_view']})
        if self.can_access('expenses'):
            money_items.append({'label': 'Expenses', 'icon': 'fas fa-receipt',
                                 'url': 'expenses.index', 'bp': 'expenses'})
        if self.can_access('cash_decl'):
            money_items.append({'label': 'Cash Declarations', 'icon': 'fas fa-cash-register',
                                 'url': 'cash_decl.index', 'bp': 'cash_decl'})
        if money_items:
            sections.append({'label': 'Money', 'icon': 'fas fa-money-bill-wave', 'items': money_items})

        # ── REPORTS ──────────────────────────────────────────────────────
        report_items = []
        if self.can_access('reports'):
            report_items.append({'label': 'Reports', 'icon': 'fas fa-chart-bar',
                 'url': 'reports.index', 'bp': 'reports'})
        if self.can_access('insights'):
            report_items.append({'label': 'AI Insights', 'icon': 'fas fa-brain',
                 'url': 'insights.index', 'bp': 'insights'})
        if report_items:
            sections.append({'label': 'Reports', 'icon': 'fas fa-chart-bar', 'items': report_items})

        # ── ADMIN ────────────────────────────────────────────────────────
        if self.role == 'admin':
            sections.append({'label': 'System', 'icon': 'fas fa-cog', 'items': [
                {'label': 'Users', 'icon': 'fas fa-users-cog', 'url': 'auth.users', 'bp': 'auth'},
                {'label': 'Audit Trail', 'icon': 'fas fa-shield-alt', 'url': 'audit.index', 'bp': 'audit'},
                {'label': 'Settings', 'icon': 'fas fa-cog', 'url': 'settings.index', 'bp': 'settings'},
            ]})

        # Drop links to endpoints that aren't registered yet (unbuilt modules)
        from flask import current_app
        for section in sections:
            section['items'] = [i for i in section['items'] if i['url'] in current_app.view_functions]
        return [s for s in sections if s['items']]

    def to_dict(self):
        return {
            'id': self.id, 'username': self.username,
            'email': self.email, 'full_name': self.full_name,
            'role': self.role, 'role_label': self.role_label,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
