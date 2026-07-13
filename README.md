# Van Sales V3 ERP System

A complete enterprise-grade Van Sales ERP built with Flask, SQLite, Bootstrap 5.

---

## ?? QUICK START IN VS CODE

### Step 1 — Prerequisites
Make sure you have installed:
- **Python 3.10+** → https://python.org/downloads
- **VS Code** → https://code.visualstudio.com

### Step 2 — Open the Project
```
File → Open Folder → select van_sales_v3/
```
Or double-click `van_sales_v3.code-workspace`

### Step 3 — Create Virtual Environment
Open **Terminal** in VS Code (`Ctrl + `` ` ``):

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### Step 4 — Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 5 — Configure Environment
Edit `.env` to set your company details and SMS API keys:
```
COMPANY_NAME=Your Company Name
COMPANY_PHONE=+233 XX XXX XXXX
COMPANY_EMAIL=info@yourcompany.com
COMPANY_ADDRESS=Your Address, Ghana

# SMS (optional - Arkesel or Hubtel)
SMS_PROVIDER=arkesel
ARKESEL_API_KEY=your_key_here
```

### Step 6 — Run the App
```bash
python run.py
```

Open your browser: **http://127.0.0.1:5000**

### Default Login
| Field    | Value      |
|----------|------------|
| Username | `admin`    |
| Password | `admin123` |

> ⚠️ **Change the admin password immediately after first login!**

---

## ?? Project Structure

```
van_sales_v3/
├── app.py                  # Main Flask app factory
├── run.py                  # Entry point
├── requirements.txt        # Python packages
├── .env                    # Configuration (edit this!)
│
├── models/                 # SQLAlchemy database models
│   ├── user.py             # Users & roles
│   ├── customer.py         # Customers CRM
│   ├── product.py          # Products & categories
│   ├── sale.py             # Sales & line items
│   ├── payment.py          # Payments
│   ├── van.py              # Vans, Drivers, Routes, Visits
│   └── notification.py     # Inventory, Returns, Suppliers,
│                           # Expenses, SMS logs, Notifications
│
├── routes/                 # Flask blueprints (URL handlers)
│   ├── auth.py             # Login, logout, users
│   ├── dashboard.py        # Dashboard & charts API
│   ├── customers.py        # Customer CRUD
│   ├── products.py         # Product CRUD
│   ├── inventory.py        # Stock management
│   ├── sales.py            # POS & sales
│   ├── invoices.py         # Invoice view & PDF
│   ├── payments.py         # Payment recording
│   ├── returns.py          # Returns management
│   ├── vans.py             # Van management
│   ├── drivers.py          # Driver management
│   ├── route_management.py # Route planning
│   ├── visits.py           # Customer visit tracking
│   ├── suppliers.py        # Supplier management
│   ├── expenses.py         # Expense tracking
│   ├── sms.py              # SMS automation
│   ├── notifications.py    # System notifications
│   ├── reports.py          # Reports & Excel export
│   └── api.py              # REST API endpoints
│
├── services/               # Business logic services
│   ├── sms_service.py      # Arkesel/Hubtel SMS
│   ├── pdf_service.py      # ReportLab PDF invoices
│   ├── notification_service.py  # Auto notifications
│   └── sequence.py         # Document numbering
│
├── templates/              # Jinja2 HTML templates
│   ├── base.html           # Master layout (sidebar, topbar)
│   ├── auth/               # Login, profile, users
│   ├── dashboard/          # Dashboard with charts
│   ├── customers/          # Customer CRM
│   ├── products/           # Product management
│   ├── inventory/          # Stock management
│   ├── sales/              # POS & sales list
│   ├── invoices/           # Invoice viewer
│   ├── payments/           # Payments & outstanding
│   ├── returns/            # Returns
│   ├── vans/               # Fleet management
│   ├── drivers/            # Drivers
│   ├── routes/             # Route planning
│   ├── visits/             # Customer visits
│   ├── suppliers/          # Suppliers
│   ├── expenses/           # Expenses
│   ├── sms/                # SMS center
│   ├── notifications/      # Alerts
│   └── reports/            # Reports & exports
│
└── static/
    ├── css/main.css         # Full ERP stylesheet (dark/light)
    └── js/main.js           # Charts, DataTables, toasts
```

---

## ?? User Roles

| Role           | View | Add | Edit | Delete | Approve |
|----------------|------|-----|------|--------|---------|
| Admin          | ✅   | ✅  | ✅   | ✅     | ✅      |
| Manager        | ✅   | ✅  | ✅   | ❌     | ✅      |
| Supervisor     | ✅   | ✅  | ✅   | ❌     | ❌      |
| Sales Rep      | ✅   | ✅  | ❌   | ❌     | ❌      |
| Driver         | ✅   | ❌  | ❌   | ❌     | ❌      |

---

## ?? Key Features

- **Dashboard** — KPI cards + 4 live charts (Chart.js)
- **POS Sales Screen** — Product search, cart, discounts, taxes
- **Professional Invoices** — HTML + downloadable PDF (ReportLab)
- **Payment Collection** — Cash, Mobile Money, Bank Transfer, Cheque
- **Customer CRM** — GPS capture, credit limits, visit history
- **Inventory Management** — Stock in/out, adjustments, movement history
- **Van & Driver Management** — Fleet tracking, license expiry alerts
- **Route Planning** — Customer assignment, visit scheduling
- **SMS Automation** — Arkesel & Hubtel (invoice, payment, overdue)
- **Excel Reports** — Pandas + OpenPyXL export
- **Dark / Light Theme** — Toggle in the topbar
- **Fully Responsive** — Works on desktop and mobile

---

## ?? SMS Setup

### Arkesel (recommended for Ghana)
1. Sign up at https://arkesel.com
2. Get your API key from the dashboard
3. Set in `.env`:
   ```
   SMS_PROVIDER=arkesel
   ARKESEL_API_KEY=your_api_key
   ARKESEL_SMS_NAME=YourBrand
   ```

### Hubtel
1. Sign up at https://hubtel.com
2. Set in `.env`:
   ```
   SMS_PROVIDER=hubtel
   HUBTEL_CLIENT_ID=your_client_id
   HUBTEL_CLIENT_SECRET=your_client_secret
   ```

---

## ??️ Database

The app uses **SQLite** — no server needed. The database file `van_sales_v3.db`
is created automatically in the project root on first run.

To reset the database:
```bash
# Delete and restart
del van_sales_v3.db    # Windows
rm van_sales_v3.db     # Mac/Linux
python run.py
```

---

## 🌐 Hosting on the Internet (Render — free to start)

This app runs locally on SQLite, but SQLite's data file gets wiped on most
hosting platforms every time the app restarts. Going live uses a real
Postgres database instead — the app already supports this out of the box
(`DATABASE_URL` env var), you don't need to change any code.

### Step 1 — Push this project to GitHub
1. Create a free account at https://github.com if you don't have one.
2. Create a new (private is fine) repository, e.g. `van-sales-v3`.
3. From this project folder:
   ```bash
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/YOUR_USERNAME/van-sales-v3.git
   git push -u origin main
   ```

### Step 2 — Create a Render account and deploy
1. Sign up free at https://render.com (you can sign in with GitHub).
2. Click **New → Blueprint**, then pick your `van-sales-v3` repo.
3. Render reads `render.yaml` in this project automatically — it creates
   both the web service *and* a free Postgres database, and wires
   `DATABASE_URL` between them for you. Click **Apply**.
4. Before the first deploy finishes, open the web service's **Environment**
   tab and add:
   - `ADMIN_PASSWORD` — a strong password for your admin account (otherwise
     it defaults to `admin123`, which anyone can guess on a public site).
5. Wait for the build to finish, then open the `.onrender.com` URL Render
   gives you — that's your app, live on the internet.

### Step 3 — Immediately after your first deploy
- Log in as `admin` and change the password from the app itself too
  (Settings → Profile), even if you set `ADMIN_PASSWORD`.
- Do **not** set `SEED_DEMO_USERS=true` on the hosted copy — those 5 demo
  accounts (manager1, cashier1, etc.) all share the password `demo1234`,
  fine for local testing, not for the internet.
- Uploaded logos/avatars are **not** persisted on Render's free tier (the
  disk resets on redeploy) — customer/sales/payment data in Postgres is
  safe either way, only re-uploadable files like logos are affected.

### Bringing your existing local data with you
Your current customers, sales, and payments live in the local SQLite file
and won't automatically appear on the hosted Postgres database — that
needs a one-time data export/import. Ask for help with this before your
first real deploy if you want to carry existing records over instead of
starting fresh.

---

## 🖥️ VS Code Debug

Press **F5** to launch the debugger using the pre-configured `.vscode` settings,
or use the **Run and Debug** panel.

---

## ?? License

Built for FMCG distribution companies in Ghana and West Africa.
Customise freely for your business needs.
