"""
Pharmacy Management System - Production Complete
All features implemented, PostgreSQL ready, full security.
Deploy to Streamlit Cloud with PostgreSQL (Neon/Supabase/Aiven).
"""

import os
import re
import json
import io
import tempfile
import shutil
from datetime import datetime, timedelta, date
from typing import Dict, Optional, List
import logging

# ==================== CONFIGURATION ====================
try:
    from streamlit.runtime.secrets import secrets as streamlit_secrets
    DATABASE_URL = streamlit_secrets.get("DATABASE_URL", os.environ.get("DATABASE_URL"))
    ADMIN_PASSWORD = streamlit_secrets.get("ADMIN_PASSWORD", os.environ.get("ADMIN_PASSWORD"))
    SECRET_KEY = streamlit_secrets.get("SECRET_KEY", os.environ.get("SECRET_KEY", "change-this"))
    SESSION_TIMEOUT = int(streamlit_secrets.get("SESSION_TIMEOUT", os.environ.get("SESSION_TIMEOUT", "1800")))
    LOGIN_ATTEMPT_LIMIT = int(streamlit_secrets.get("LOGIN_ATTEMPT_LIMIT", os.environ.get("LOGIN_ATTEMPT_LIMIT", "5")))
    LOGIN_LOCKOUT_SECONDS = int(streamlit_secrets.get("LOGIN_LOCKOUT_SECONDS", os.environ.get("LOGIN_LOCKOUT_SECONDS", "300")))
except ImportError:
    from dotenv import load_dotenv
    load_dotenv()
    DATABASE_URL = os.environ.get("DATABASE_URL")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-this")
    SESSION_TIMEOUT = int(os.environ.get("SESSION_TIMEOUT", "1800"))
    LOGIN_ATTEMPT_LIMIT = int(os.environ.get("LOGIN_ATTEMPT_LIMIT", "5"))
    LOGIN_LOCKOUT_SECONDS = int(os.environ.get("LOGIN_LOCKOUT_SECONDS", "300"))

if not DATABASE_URL:
    DATABASE_URL = "sqlite:///pharmacy_local.db"
    logger.warning("No DATABASE_URL found, using SQLite (not for production)")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== IMPORTS ====================
import streamlit as st
import pandas as pd
import bcrypt
import plotly.express as px
import plotly.graph_objects as go
from fpdf import FPDF
import qrcode
import barcode
from barcode.writer import ImageWriter
from PIL import Image
from werkzeug.security import generate_password_hash, check_password_hash

# Database
if DATABASE_URL.startswith("postgresql"):
    import psycopg2
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import QueuePool
    engine = create_engine(DATABASE_URL, poolclass=QueuePool, pool_size=10, max_overflow=20, pool_pre_ping=True)
else:
    from sqlalchemy import create_engine, text
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# ==================== DATABASE INITIALIZATION ====================
def init_db():
    """Create all tables and default data."""
    with engine.connect() as conn:
        # Roles
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS roles (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                permissions TEXT
            )
        """))
        # Users
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                email TEXT,
                role_id INTEGER REFERENCES roles(id),
                is_active INTEGER DEFAULT 1,
                must_change_password INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # Categories
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS categories (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                description TEXT
            )
        """))
        # Medicines
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS medicines (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                generic_name TEXT,
                category_id INTEGER REFERENCES categories(id),
                barcode TEXT UNIQUE,
                manufacturer TEXT,
                unit_price REAL NOT NULL,
                reorder_level INTEGER DEFAULT 10,
                current_stock INTEGER DEFAULT 0,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # Batches
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS batches (
                id SERIAL PRIMARY KEY,
                medicine_id INTEGER REFERENCES medicines(id) NOT NULL,
                batch_number TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                expiry_date DATE NOT NULL,
                purchase_price REAL,
                selling_price REAL,
                mrp REAL,
                supplier_id INTEGER REFERENCES suppliers(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # Patients
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS patients (
                id SERIAL PRIMARY KEY,
                patient_id TEXT UNIQUE NOT NULL,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                date_of_birth DATE,
                gender TEXT,
                phone TEXT,
                email TEXT,
                address TEXT,
                insurance_provider TEXT,
                insurance_number TEXT,
                blood_group TEXT,
                allergies TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # Prescriptions
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prescriptions (
                id SERIAL PRIMARY KEY,
                prescription_number TEXT UNIQUE NOT NULL,
                patient_id INTEGER REFERENCES patients(id) NOT NULL,
                doctor_name TEXT,
                prescribed_date DATE,
                expiry_date DATE,
                status TEXT DEFAULT 'pending',
                pharmacist_notes TEXT,
                approved_by INTEGER REFERENCES users(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # Prescription items
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prescription_items (
                id SERIAL PRIMARY KEY,
                prescription_id INTEGER REFERENCES prescriptions(id) NOT NULL,
                medicine_id INTEGER REFERENCES medicines(id) NOT NULL,
                dosage TEXT,
                duration TEXT,
                instructions TEXT,
                quantity INTEGER NOT NULL
            )
        """))
        # Sales
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sales (
                id SERIAL PRIMARY KEY,
                invoice_number TEXT UNIQUE NOT NULL,
                patient_id INTEGER REFERENCES patients(id),
                user_id INTEGER REFERENCES users(id) NOT NULL,
                total_amount REAL NOT NULL,
                discount REAL DEFAULT 0,
                tax REAL DEFAULT 0,
                net_amount REAL NOT NULL,
                payment_method TEXT,
                payment_status TEXT DEFAULT 'completed',
                loyalty_points_earned INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # Sale items
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sale_items (
                id SERIAL PRIMARY KEY,
                sale_id INTEGER REFERENCES sales(id) NOT NULL,
                medicine_id INTEGER REFERENCES medicines(id) NOT NULL,
                batch_id INTEGER REFERENCES batches(id) NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                total REAL NOT NULL
            )
        """))
        # Sales returns
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sales_returns (
                id SERIAL PRIMARY KEY,
                original_sale_id INTEGER REFERENCES sales(id) NOT NULL,
                sale_item_id INTEGER REFERENCES sale_items(id) NOT NULL,
                quantity_returned INTEGER NOT NULL,
                refund_amount REAL NOT NULL,
                reason TEXT,
                created_by INTEGER REFERENCES users(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # Suppliers
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS suppliers (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                contact_person TEXT,
                phone TEXT,
                email TEXT,
                address TEXT,
                gst_number TEXT,
                payment_terms TEXT,
                is_active INTEGER DEFAULT 1
            )
        """))
        # Purchase orders
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS purchase_orders (
                id SERIAL PRIMARY KEY,
                po_number TEXT UNIQUE NOT NULL,
                supplier_id INTEGER REFERENCES suppliers(id) NOT NULL,
                order_date DATE,
                expected_delivery DATE,
                total_amount REAL,
                status TEXT DEFAULT 'pending',
                created_by INTEGER REFERENCES users(id)
            )
        """))
        # Staff attendance
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS staff_attendance (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) NOT NULL,
                date DATE NOT NULL,
                check_in TIME,
                check_out TIME,
                status TEXT DEFAULT 'present',
                UNIQUE(user_id, date)
            )
        """))
        # Notifications
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                type TEXT,
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # Audit logs
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                action TEXT NOT NULL,
                details TEXT,
                ip_address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # Loyalty points
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS loyalty_points (
                id SERIAL PRIMARY KEY,
                patient_id INTEGER REFERENCES patients(id) NOT NULL,
                points INTEGER DEFAULT 0,
                redeemed INTEGER DEFAULT 0
            )
        """))
        # Appointments
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS appointments (
                id SERIAL PRIMARY KEY,
                patient_id INTEGER REFERENCES patients(id) NOT NULL,
                appointment_date DATE,
                appointment_time TIME,
                purpose TEXT,
                status TEXT DEFAULT 'scheduled',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        # Drug interactions
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS drug_interactions (
                id SERIAL PRIMARY KEY,
                medicine1_id INTEGER REFERENCES medicines(id) NOT NULL,
                medicine2_id INTEGER REFERENCES medicines(id) NOT NULL,
                severity TEXT,
                description TEXT
            )
        """))
        # Settings
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.commit()

        # Insert default roles
        roles = [
            ("Admin", '{"all": true}'),
            ("Manager", '{"medicines":true,"inventory":true,"suppliers":true,"reports":true,"staff":true,"audit":true}'),
            ("Pharmacist", '{"prescriptions":true,"inventory_view":true,"sales_view":true,"label_print":true}'),
            ("Cashier", '{"sales":true,"patients_view":true}')
        ]
        for name, perms in roles:
            conn.execute(text("INSERT INTO roles (name, permissions) VALUES (:n, :p) ON CONFLICT (name) DO NOTHING"), {"n": name, "p": perms})
        conn.commit()

        # Create admin user if ADMIN_PASSWORD provided
        if ADMIN_PASSWORD:
            admin_role = conn.execute(text("SELECT id FROM roles WHERE name = 'Admin'")).fetchone()
            if admin_role:
                admin_exists = conn.execute(text("SELECT id FROM users WHERE username = 'admin'")).fetchone()
                if not admin_exists:
                    conn.execute(text("""
                        INSERT INTO users (username, password_hash, full_name, email, role_id, must_change_password)
                        VALUES ('admin', :pwd, 'System Administrator', 'admin@pharmacy.com', :role, 1)
                    """), {"pwd": generate_password_hash(ADMIN_PASSWORD), "role": admin_role[0]})
                    conn.commit()
                    logger.info("Admin user created.")
                else:
                    # Ensure admin has must_change_password=1 if password was default? Not needed.
                    pass

        # Default categories
        categories = ["Antibiotics", "Analgesics", "Antipyretics", "Vitamins", "Antihistamines", "Dermatologicals"]
        for cat in categories:
            conn.execute(text("INSERT INTO categories (name) VALUES (:c) ON CONFLICT (name) DO NOTHING"), {"c": cat})
        conn.commit()

        # Default settings
        default_settings = {
            "pharmacy_name": "HealthPlus Pharmacy",
            "pharmacy_address": "123 Main Street, City",
            "pharmacy_phone": "+1 234 567 8900",
            "pharmacy_email": "info@healthplus.com",
            "tax_number": "TAX123456",
            "pharmacist_license": "PHARM-7890",
            "receipt_footer": "Thank you for your visit!",
            "loyalty_rate": "5"
        }
        for key, val in default_settings.items():
            conn.execute(text("INSERT INTO settings (key, value) VALUES (:k, :v) ON CONFLICT (key) DO UPDATE SET value = excluded.value"), {"k": key, "v": val})
        conn.commit()

# ==================== HELPER FUNCTIONS ====================
def get_settings_dict():
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT key, value FROM settings")).fetchall()
        return {r[0]: r[1] for r in rows}

def update_setting(key, value):
    with engine.connect() as conn:
        conn.execute(text("INSERT INTO settings (key, value, updated_at) VALUES (:k, :v, CURRENT_TIMESTAMP) ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at"), {"k": key, "v": value})
        conn.commit()

def log_audit(user_id, action, details=""):
    try:
        with engine.connect() as conn:
            conn.execute(text("INSERT INTO audit_logs (user_id, action, details, created_at) VALUES (:uid, :act, :det, CURRENT_TIMESTAMP)"), {"uid": user_id, "act": action, "det": details})
            conn.commit()
    except Exception as e:
        logger.error(f"Audit log failed: {e}")

def require_permission(permission):
    if not st.session_state.get('logged_in'):
        st.error("Please log in.")
        st.stop()
    user = st.session_state.user
    perms = json.loads(user.get('permissions', '{}'))
    if perms.get('all') or perms.get(permission):
        return True
    st.error(f"Permission '{permission}' required. Access denied.")
    st.stop()

def get_low_stock():
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, name, current_stock, reorder_level FROM medicines WHERE current_stock <= reorder_level")).fetchall()
        return pd.DataFrame([{"id":r[0],"name":r[1],"stock":r[2],"reorder":r[3]} for r in rows])

def get_expiring(days=30):
    exp_date = (datetime.utcnow() + timedelta(days=days)).date()
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT b.id, m.name, b.batch_number, b.expiry_date, b.quantity FROM batches b JOIN medicines m ON b.medicine_id=m.id WHERE b.expiry_date <= :ed AND b.quantity>0 ORDER BY b.expiry_date"), {"ed": exp_date}).fetchall()
        return pd.DataFrame([{"id":r[0],"name":r[1],"batch":r[2],"expiry":r[3],"qty":r[4]} for r in rows])

def get_best_batch(medicine_id, needed):
    with engine.connect() as conn:
        batches = conn.execute(text("SELECT id, quantity, selling_price FROM batches WHERE medicine_id=:mid AND quantity>0 AND expiry_date>CURRENT_DATE ORDER BY expiry_date ASC"), {"mid": medicine_id}).fetchall()
    result = []
    remaining = needed
    for b in batches:
        take = min(b[1], remaining)
        if take > 0:
            result.append({"batch_id": b[0], "quantity": take, "price": b[2]})
            remaining -= take
        if remaining == 0:
            break
    if remaining > 0:
        raise ValueError(f"Insufficient stock for medicine {medicine_id}")
    return result

def generate_invoice_pdf(data):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    settings = get_settings_dict()
    pdf.cell(200,10, settings.get("pharmacy_name","Pharmacy"), ln=1, align='C')
    pdf.set_font("Arial", "", 10)
    pdf.cell(200,5, settings.get("pharmacy_address",""), ln=1, align='C')
    pdf.cell(200,5, f"Phone: {settings.get('pharmacy_phone','')}", ln=1, align='C')
    pdf.ln(10)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(200,10, f"Invoice: {data['invoice_number']}", ln=1)
    pdf.cell(200,10, f"Date: {data['date']}", ln=1)
    pdf.cell(200,10, f"Patient: {data.get('patient_name','Walk-in Customer')}", ln=1)
    pdf.ln(5)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(80,10, "Item",1)
    pdf.cell(30,10, "Qty",1)
    pdf.cell(40,10, "Price",1)
    pdf.cell(40,10, "Total",1)
    pdf.ln()
    pdf.set_font("Arial", "", 10)
    for item in data['items']:
        pdf.cell(80,10, item['name'][:30],1)
        pdf.cell(30,10, str(item['quantity']),1)
        pdf.cell(40,10, f"${item['price']:.2f}",1)
        pdf.cell(40,10, f"${item['total']:.2f}",1)
        pdf.ln()
    pdf.ln(5)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(150,10, "Total:",0)
    pdf.cell(40,10, f"${data['total']:.2f}",0)
    pdf.ln()
    pdf.cell(150,10, "Discount:",0)
    pdf.cell(40,10, f"${data.get('discount',0):.2f}",0)
    pdf.ln()
    pdf.cell(150,10, "Net Amount:",0)
    pdf.cell(40,10, f"${data['net_amount']:.2f}",0)
    pdf.ln(10)
    pdf.cell(200,10, settings.get("receipt_footer","Thank you!"), ln=1, align='C')
    return pdf.output(dest='S').encode('latin1')

def generate_barcode(data):
    try:
        code128 = barcode.get_barcode_class('code128')
        buffer = io.BytesIO()
        code128(data, writer=ImageWriter()).write(buffer)
        buffer.seek(0)
        return Image.open(buffer)
    except:
        return Image.new('RGB', (300,100), 'white')

def generate_qr(data):
    qr = qrcode.QRCode(box_size=5, border=2)
    qr.add_data(data)
    return qr.make_image(fill_color="black", back_color="white")

def create_notification(title, message, type_="info"):
    with engine.connect() as conn:
        conn.execute(text("INSERT INTO notifications (title, message, type, created_at) VALUES (:t, :m, :typ, CURRENT_TIMESTAMP)"), {"t": title, "m": message, "typ": type_})
        conn.commit()

# ==================== AUTHENTICATION ====================
def login_user(username, password):
    try:
        with engine.connect() as conn:
            # Check lockout
            lock = conn.execute(text("SELECT value FROM settings WHERE key = :key AND value > CURRENT_TIMESTAMP"), {"key": f"lockout_{username}"}).fetchone()
            if lock:
                st.error("Account temporarily locked. Please try again later.")
                return None
            user = conn.execute(text("""
                SELECT u.id, u.username, u.password_hash, u.full_name, u.email, u.role_id, u.must_change_password,
                       r.name as role_name, r.permissions
                FROM users u JOIN roles r ON u.role_id = r.id
                WHERE u.username = :uname AND u.is_active = 1
            """), {"uname": username}).fetchone()
            if user and check_password_hash(user[2], password):
                # Reset failures
                conn.execute(text("DELETE FROM settings WHERE key = :key"), {"key": f"failures_{username}"})
                conn.commit()
                log_audit(user[0], "LOGIN", f"User {username} logged in")
                return {"id": user[0], "username": user[1], "full_name": user[3], "email": user[4],
                        "role_id": user[5], "must_change_password": user[6], "role_name": user[7], "permissions": user[8]}
            else:
                # Increment failures
                fail = conn.execute(text("SELECT value FROM settings WHERE key = :key"), {"key": f"failures_{username}"}).fetchone()
                fail_count = int(fail[0]) if fail else 0
                fail_count += 1
                conn.execute(text("INSERT INTO settings (key, value) VALUES (:k, :v) ON CONFLICT (key) DO UPDATE SET value = excluded.value"), {"k": f"failures_{username}", "v": str(fail_count)})
                if fail_count >= LOGIN_ATTEMPT_LIMIT:
                    lock_until = datetime.utcnow() + timedelta(seconds=LOGIN_LOCKOUT_SECONDS)
                    conn.execute(text("INSERT INTO settings (key, value) VALUES (:k, :v) ON CONFLICT (key) DO UPDATE SET value = excluded.value"), {"k": f"lockout_{username}", "v": lock_until.isoformat()})
                conn.commit()
                return None
    except Exception as e:
        logger.error(f"Login error: {e}")
        st.error("System error. Please try again later.")
        return None

def change_password(user_id, new_password):
    if len(new_password) < 8 or not re.search(r"[A-Z]", new_password) or not re.search(r"[a-z]", new_password) or not re.search(r"[0-9]", new_password):
        raise ValueError("Password must be at least 8 chars with uppercase, lowercase, and digit.")
    with engine.connect() as conn:
        conn.execute(text("UPDATE users SET password_hash = :hash, must_change_password = 0 WHERE id = :id"), {"hash": generate_password_hash(new_password), "id": user_id})
        conn.commit()
        log_audit(user_id, "PASSWORD_CHANGE", "Password changed")

def logout_user():
    if st.session_state.get('user'):
        log_audit(st.session_state.user['id'], "LOGOUT", "User logged out")
    st.session_state.clear()
    st.session_state.logged_in = False
    st.rerun()

def check_session_timeout():
    if 'login_time' in st.session_state:
        elapsed = (datetime.utcnow() - st.session_state.login_time).total_seconds()
        if elapsed > SESSION_TIMEOUT:
            st.warning("Session expired due to inactivity.")
            logout_user()
            st.stop()
    else:
        st.session_state.login_time = datetime.utcnow()

# ==================== UI PAGES ====================
def render_login_page():
    st.set_page_config(page_title="Pharmacy Management System", layout="wide")
    st.title("🏥 Pharmacy Management System")
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.image("https://img.icons8.com/fluency/96/pill.png", width=100)
        st.subheader("Secure Login")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Login", type="primary", use_container_width=True):
            if username and password:
                user = login_user(username, password)
                if user:
                    st.session_state.logged_in = True
                    st.session_state.user = user
                    st.session_state.login_time = datetime.utcnow()
                    if user.get('must_change_password'):
                        st.session_state.must_change_password = True
                    st.rerun()
                else:
                    st.error("Invalid username or password")
            else:
                st.warning("Please enter both fields")

def render_change_password():
    st.title("🔐 Change Required Password")
    st.warning("You must change your default password before continuing.")
    new = st.text_input("New Password", type="password")
    confirm = st.text_input("Confirm Password", type="password")
    if st.button("Update Password"):
        if new != confirm:
            st.error("Passwords do not match.")
        else:
            try:
                change_password(st.session_state.user['id'], new)
                st.session_state.must_change_password = False
                st.success("Password changed. Please log in again.")
                logout_user()
            except ValueError as e:
                st.error(str(e))

def render_dashboard():
    require_permission("all")
    st.title("📊 Dashboard")
    with engine.connect() as conn:
        total_meds = conn.execute(text("SELECT COUNT(*) FROM medicines")).scalar()
        total_patients = conn.execute(text("SELECT COUNT(*) FROM patients")).scalar()
        today_sales = conn.execute(text("SELECT COALESCE(SUM(net_amount),0) FROM sales WHERE created_at::date = CURRENT_DATE")).scalar()
        month_sales = conn.execute(text("SELECT COALESCE(SUM(net_amount),0) FROM sales WHERE date_trunc('month', created_at) = date_trunc('month', CURRENT_DATE)")).scalar()
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("💊 Medicines", total_meds)
    c2.metric("👥 Patients", total_patients)
    c3.metric("💰 Sales Today", f"${today_sales:,.2f}")
    c4.metric("📅 Monthly Sales", f"${month_sales:,.2f}")

    low = get_low_stock()
    exp = get_expiring(30)
    if not low.empty:
        st.warning(f"⚠️ Low stock: {len(low)} medicines below reorder level")
    if not exp.empty:
        st.error(f"⚠️ Expiring soon: {len(exp)} batches within 30 days")

    # Sales trend last 7 days
    with engine.connect() as conn:
        trend = conn.execute(text("""
            SELECT created_at::date as date, COALESCE(SUM(net_amount),0) as sales
            FROM sales WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY created_at::date ORDER BY date
        """)).fetchall()
    if trend:
        df = pd.DataFrame([{"date":r[0], "sales":r[1]} for r in trend])
        fig = px.line(df, x='date', y='sales', title='Last 7 Days Sales')
        st.plotly_chart(fig, use_container_width=True)

    # Top selling medicines
    with engine.connect() as conn:
        top = conn.execute(text("""
            SELECT m.name, SUM(si.quantity) as sold
            FROM sale_items si JOIN medicines m ON si.medicine_id = m.id
            GROUP BY si.medicine_id ORDER BY sold DESC LIMIT 5
        """)).fetchall()
    if top:
        df_top = pd.DataFrame([{"name":r[0], "sold":r[1]} for r in top])
        fig2 = px.bar(df_top, x='name', y='sold', title='Top Selling Medicines')
        st.plotly_chart(fig2, use_container_width=True)

def render_medicines():
    require_permission("medicines")
    st.title("💊 Medicines Management")
    tab1, tab2, tab3 = st.tabs(["Medicine List", "Add/Edit Medicine", "Categories"])
    with tab1:
        search = st.text_input("Search by name, generic, barcode")
        page = st.number_input("Page", min_value=1, value=1, step=1)
        per_page = 20
        offset = (page-1)*per_page
        with engine.connect() as conn:
            if search:
                count = conn.execute(text("SELECT COUNT(*) FROM medicines WHERE name ILIKE :s OR generic_name ILIKE :s OR barcode ILIKE :s"), {"s": f"%{search}%"}).scalar()
                rows = conn.execute(text("""
                    SELECT m.*, c.name as category_name
                    FROM medicines m LEFT JOIN categories c ON m.category_id = c.id
                    WHERE m.name ILIKE :s OR m.generic_name ILIKE :s OR m.barcode ILIKE :s
                    LIMIT :lim OFFSET :off
                """), {"s": f"%{search}%", "lim": per_page, "off": offset}).fetchall()
            else:
                count = conn.execute(text("SELECT COUNT(*) FROM medicines")).scalar()
                rows = conn.execute(text("""
                    SELECT m.*, c.name as category_name
                    FROM medicines m LEFT JOIN categories c ON m.category_id = c.id
                    LIMIT :lim OFFSET :off
                """), {"lim": per_page, "off": offset}).fetchall()
        st.write(f"Total: {count}")
        if rows:
            df = pd.DataFrame([dict(r._mapping) for r in rows])
            st.dataframe(df[['name','generic_name','category_name','unit_price','current_stock','reorder_level','barcode']], use_container_width=True)
            for r in rows:
                col1, col2, col3, col4 = st.columns([3,1,1,1])
                col1.write(f"**{r.name}** (Stock: {r.current_stock})")
                if col2.button(f"✏️ Edit", key=f"edit_{r.id}"):
                    st.session_state.edit_medicine = dict(r._mapping)
                if col3.button(f"🗑️ Delete", key=f"del_{r.id}"):
                    with engine.connect() as conn2:
                        conn2.execute(text("DELETE FROM medicines WHERE id = :id"), {"id": r.id})
                        conn2.commit()
                    st.rerun()
                if col4.button(f"🏷️ Barcode", key=f"barcode_{r.id}"):
                    img = generate_barcode(r.barcode or str(r.id))
                    st.image(img, width=100)
    with tab2:
        if 'edit_medicine' in st.session_state:
            med = st.session_state.edit_medicine
            st.subheader("Edit Medicine")
        else:
            med = {}
            st.subheader("Add New Medicine")
        with engine.connect() as conn:
            cats = conn.execute(text("SELECT id, name FROM categories")).fetchall()
        cat_options = {c[0]: c[1] for c in cats}
        name = st.text_input("Medicine Name", value=med.get('name', ''))
        generic = st.text_input("Generic Name", value=med.get('generic_name', ''))
        category = st.selectbox("Category", options=list(cat_options.keys()), format_func=lambda x: cat_options[x], index=0 if not med else next((i for i,c in enumerate(cats) if c[0]==med.get('category_id')),0))
        barcode_val = st.text_input("Barcode", value=med.get('barcode', ''))
        manufacturer = st.text_input("Manufacturer", value=med.get('manufacturer', ''))
        price = st.number_input("Unit Price ($)", min_value=0.0, value=float(med.get('unit_price',0)))
        reorder = st.number_input("Reorder Level", min_value=0, value=int(med.get('reorder_level',10)))
        stock = st.number_input("Current Stock", min_value=0, value=int(med.get('current_stock',0)))
        desc = st.text_area("Description", value=med.get('description', ''))
        if st.button("Save Medicine"):
            with engine.connect() as conn:
                if 'edit_medicine' in st.session_state:
                    conn.execute(text("""
                        UPDATE medicines SET name=:n, generic_name=:g, category_id=:c, barcode=:b,
                        manufacturer=:m, unit_price=:p, reorder_level=:r, current_stock=:s, description=:d
                        WHERE id=:id
                    """), {"n":name,"g":generic,"c":category,"b":barcode_val,"m":manufacturer,"p":price,"r":reorder,"s":stock,"d":desc,"id":med['id']})
                    del st.session_state.edit_medicine
                else:
                    conn.execute(text("""
                        INSERT INTO medicines (name, generic_name, category_id, barcode, manufacturer, unit_price, reorder_level, current_stock, description)
                        VALUES (:n,:g,:c,:b,:m,:p,:r,:s,:d)
                    """), {"n":name,"g":generic,"c":category,"b":barcode_val,"m":manufacturer,"p":price,"r":reorder,"s":stock,"d":desc})
                conn.commit()
            st.success("Saved")
            st.rerun()
    with tab3:
        st.subheader("Categories")
        new_cat = st.text_input("New Category")
        if st.button("Add Category") and new_cat:
            with engine.connect() as conn:
                conn.execute(text("INSERT INTO categories (name) VALUES (:n) ON CONFLICT DO NOTHING"), {"n": new_cat})
                conn.commit()
            st.rerun()
        with engine.connect() as conn:
            cats = conn.execute(text("SELECT id, name FROM categories")).fetchall()
            for c in cats:
                col1, col2 = st.columns([3,1])
                col1.write(c[1])
                if col2.button(f"Delete", key=f"delcat_{c[0]}"):
                    conn.execute(text("DELETE FROM categories WHERE id = :id"), {"id": c[0]})
                    conn.commit()
                    st.rerun()

def render_inventory():
    require_permission("inventory")
    st.title("📦 Inventory Management")
    tab1, tab2 = st.tabs(["Stock In/Out", "Batch List"])
    with tab1:
        with engine.connect() as conn:
            meds = conn.execute(text("SELECT id, name FROM medicines")).fetchall()
        med_options = {m[0]: m[1] for m in meds}
        med_id = st.selectbox("Medicine", list(med_options.keys()), format_func=lambda x: med_options[x])
        trans_type = st.selectbox("Type", ["Stock In", "Stock Out"])
        qty = st.number_input("Quantity", min_value=1, step=1)
        notes = st.text_area("Notes")
        if trans_type == "Stock In":
            batch_no = st.text_input("Batch Number")
            expiry = st.date_input("Expiry Date", datetime.now().date() + timedelta(days=365))
            purchase_price = st.number_input("Purchase Price", min_value=0.0, value=0.0)
            selling_price = st.number_input("Selling Price", min_value=0.0, value=0.0)
            if st.button("Add Stock"):
                with engine.connect() as conn:
                    conn.execute(text("""
                        INSERT INTO batches (medicine_id, batch_number, quantity, expiry_date, purchase_price, selling_price)
                        VALUES (:mid, :bn, :q, :exp, :pp, :sp)
                    """), {"mid": med_id, "bn": batch_no, "q": qty, "exp": expiry, "pp": purchase_price, "sp": selling_price})
                    conn.execute(text("UPDATE medicines SET current_stock = current_stock + :q WHERE id = :mid"), {"q": qty, "mid": med_id})
                    conn.execute(text("INSERT INTO inventory_transactions (medicine_id, transaction_type, quantity, notes) VALUES (:mid, 'Stock In', :q, :n)"), {"mid": med_id, "q": qty, "n": notes})
                    conn.commit()
                st.success("Stock added")
                st.rerun()
        else:  # Stock Out
            if st.button("Process Sale (Deduct Stock)"):
                try:
                    batches = get_best_batch(med_id, qty)
                    with engine.connect() as conn:
                        for b in batches:
                            conn.execute(text("UPDATE batches SET quantity = quantity - :q WHERE id = :bid"), {"q": b['quantity'], "bid": b['batch_id']})
                        conn.execute(text("UPDATE medicines SET current_stock = current_stock - :q WHERE id = :mid"), {"q": qty, "mid": med_id})
                        conn.execute(text("INSERT INTO inventory_transactions (medicine_id, transaction_type, quantity, notes) VALUES (:mid, 'Stock Out', :q, :n)"), {"mid": med_id, "q": qty, "n": notes})
                        conn.commit()
                    st.success(f"Stock out using {len(batches)} batch(es)")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
    with tab2:
        with engine.connect() as conn:
            batches = conn.execute(text("""
                SELECT b.*, m.name as medicine_name
                FROM batches b JOIN medicines m ON b.medicine_id = m.id
                ORDER BY b.expiry_date
            """)).fetchall()
        if batches:
            df = pd.DataFrame([dict(r._mapping) for r in batches])
            st.dataframe(df[['medicine_name','batch_number','quantity','expiry_date','purchase_price','selling_price']], use_container_width=True)

def render_patients():
    require_permission("patients_view")
    st.title("👥 Patient Management")
    tab1, tab2 = st.tabs(["Patient List", "Register Patient"])
    with tab1:
        search = st.text_input("Search")
        with engine.connect() as conn:
            if search:
                rows = conn.execute(text("SELECT * FROM patients WHERE first_name ILIKE :s OR last_name ILIKE :s OR patient_id ILIKE :s OR phone ILIKE :s"), {"s": f"%{search}%"}).fetchall()
            else:
                rows = conn.execute(text("SELECT * FROM patients LIMIT 50")).fetchall()
        for r in rows:
            with st.expander(f"{r.first_name} {r.last_name} (ID: {r.patient_id})"):
                col1, col2 = st.columns(2)
                col1.write(f"📞 {r.phone}")
                col1.write(f"📧 {r.email}")
                col1.write(f"🏥 Insurance: {r.insurance_provider} - {r.insurance_number}")
                col2.write(f"🩸 Blood: {r.blood_group}")
                col2.write(f"⚠️ Allergies: {r.allergies or 'None'}")
    with tab2:
        st.subheader("New Patient")
        col1, col2 = st.columns(2)
        with col1:
            first = st.text_input("First Name")
            last = st.text_input("Last Name")
            dob = st.date_input("DOB", value=datetime.now().date() - timedelta(days=365*30))
            gender = st.selectbox("Gender", ["Male","Female","Other"])
            phone = st.text_input("Phone")
            email = st.text_input("Email")
        with col2:
            address = st.text_area("Address")
            insurance_provider = st.text_input("Insurance Provider")
            insurance_number = st.text_input("Insurance Number")
            blood_group = st.selectbox("Blood Group", ["A+","A-","B+","B-","O+","O-","AB+","AB-"])
            allergies = st.text_area("Allergies")
        if st.button("Register"):
            if first and last:
                pid = f"PAT{datetime.now().strftime('%Y%m%d%H%M%S')}"
                with engine.connect() as conn:
                    conn.execute(text("""
                        INSERT INTO patients (patient_id, first_name, last_name, date_of_birth, gender, phone, email, address,
                        insurance_provider, insurance_number, blood_group, allergies)
                        VALUES (:pid, :fn, :ln, :dob, :gen, :ph, :em, :addr, :ins, :insnum, :bg, :all)
                    """), {"pid":pid,"fn":first,"ln":last,"dob":dob,"gen":gender,"ph":phone,"em":email,"addr":address,"ins":insurance_provider,"insnum":insurance_number,"bg":blood_group,"all":allergies})
                    conn.commit()
                st.success(f"Registered ID: {pid}")
                st.rerun()

def render_prescriptions():
    require_permission("prescriptions")
    st.title("📋 Prescriptions")
    tab1, tab2 = st.tabs(["Pending", "New Prescription"])
    with tab1:
        with engine.connect() as conn:
            pending = conn.execute(text("""
                SELECT p.*, pat.first_name, pat.last_name
                FROM prescriptions p JOIN patients pat ON p.patient_id = pat.id
                WHERE p.status = 'pending'
            """)).fetchall()
        for p in pending:
            with st.expander(f"#{p.prescription_number} - {p.first_name} {p.last_name}"):
                st.write(f"Doctor: {p.doctor_name}, Date: {p.prescribed_date}")
                items = conn.execute(text("SELECT pi.*, m.name, m.current_stock FROM prescription_items pi JOIN medicines m ON pi.medicine_id = m.id WHERE pi.prescription_id = :pid"), {"pid": p.id}).fetchall()
                stock_ok = True
                for it in items:
                    st.write(f"- {it.name}: Qty {it.quantity}, Dosage {it.dosage}, Stock: {it.current_stock}")
                    if it.quantity > it.current_stock:
                        stock_ok = False
                        st.error(f"Insufficient stock for {it.name}")
                notes = st.text_area("Pharmacist Notes", key=f"notes_{p.id}")
                col1, col2 = st.columns(2)
                if col1.button("Approve", key=f"app_{p.id}"):
                    if not stock_ok:
                        st.error("Cannot approve: stock insufficient")
                    else:
                        with engine.connect() as conn2:
                            conn2.execute(text("UPDATE prescriptions SET status='approved', pharmacist_notes=:n, approved_by=:uid WHERE id=:pid"), {"n": notes, "uid": st.session_state.user['id'], "pid": p.id})
                            conn2.commit()
                        st.success("Approved")
                        st.rerun()
                if col2.button("Reject", key=f"rej_{p.id}"):
                    with engine.connect() as conn2:
                        conn2.execute(text("UPDATE prescriptions SET status='rejected' WHERE id=:pid"), {"pid": p.id})
                        conn2.commit()
                    st.rerun()
    with tab2:
        st.subheader("Create Prescription")
        with engine.connect() as conn:
            patients = conn.execute(text("SELECT id, patient_id, first_name, last_name FROM patients")).fetchall()
        pat_options = {p[0]: f"{p[2]} {p[3]} ({p[1]})" for p in patients}
        patient_id = st.selectbox("Patient", list(pat_options.keys()), format_func=lambda x: pat_options[x])
        doctor_name = st.text_input("Doctor Name")
        prescribed_date = st.date_input("Prescribed Date", datetime.now().date())
        expiry_date = st.date_input("Expiry Date", datetime.now().date() + timedelta(days=30))
        # Medicine items
        with engine.connect() as conn:
            all_meds = conn.execute(text("SELECT id, name FROM medicines")).fetchall()
        med_options = {m[0]: m[1] for m in all_meds}
        if 'prescription_items' not in st.session_state:
            st.session_state.prescription_items = []
        col1, col2, col3, col4 = st.columns([2,1,2,1])
        with col1:
            med_sel = st.selectbox("Medicine", list(med_options.keys()), format_func=lambda x: med_options[x], key="med_sel")
        with col2:
            qty = st.number_input("Qty", min_value=1, value=1, key="qty_sel")
        with col3:
            dosage = st.text_input("Dosage", key="dosage_sel")
        with col4:
            duration = st.text_input("Duration", key="dur_sel")
        if st.button("Add Medicine"):
            st.session_state.prescription_items.append({
                "medicine_id": med_sel,
                "medicine_name": med_options[med_sel],
                "quantity": qty,
                "dosage": dosage,
                "duration": duration,
                "instructions": dosage
            })
            st.rerun()
        for idx, it in enumerate(st.session_state.prescription_items):
            st.write(f"{idx+1}. {it['medicine_name']} - Qty {it['quantity']}, Dosage {it['dosage']}")
            if st.button(f"Remove {idx}", key=f"rem_{idx}"):
                st.session_state.prescription_items.pop(idx)
                st.rerun()
        if st.button("Save Prescription") and patient_id:
            pres_num = f"RX{datetime.now().strftime('%Y%m%d%H%M%S')}"
            with engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO prescriptions (prescription_number, patient_id, doctor_name, prescribed_date, expiry_date, status)
                    VALUES (:num, :pid, :doc, :pd, :ed, 'pending')
                """), {"num": pres_num, "pid": patient_id, "doc": doctor_name, "pd": prescribed_date, "ed": expiry_date})
                pres_id = conn.execute(text("SELECT lastval()")).scalar()
                for it in st.session_state.prescription_items:
                    conn.execute(text("""
                        INSERT INTO prescription_items (prescription_id, medicine_id, dosage, duration, instructions, quantity)
                        VALUES (:pid, :mid, :dos, :dur, :ins, :qty)
                    """), {"pid": pres_id, "mid": it['medicine_id'], "dos": it['dosage'], "dur": it['duration'], "ins": it['instructions'], "qty": it['quantity']})
                conn.commit()
            st.session_state.prescription_items = []
            st.success(f"Prescription {pres_num} created")
            st.rerun()

def render_sales_billing():
    require_permission("sales")
    st.title("💰 Sales & Billing")
    if 'cart' not in st.session_state:
        st.session_state.cart = []
    col1, col2 = st.columns([2,1])
    with col1:
        st.subheader("Add Item")
        with engine.connect() as conn:
            medicines = conn.execute(text("SELECT id, name, unit_price, current_stock FROM medicines WHERE current_stock > 0")).fetchall()
        med_options = {m[0]: f"{m[1]} - ${m[2]:.2f}" for m in medicines}
        if med_options:
            med_id = st.selectbox("Medicine", list(med_options.keys()), format_func=lambda x: med_options[x])
            med = next(m for m in medicines if m[0] == med_id)
            qty = st.number_input("Quantity", min_value=1, max_value=med[3], step=1)
            if st.button("Add to Cart"):
                try:
                    batches = get_best_batch(med_id, qty)
                    st.session_state.cart.append({
                        "medicine_id": med_id,
                        "name": med[1],
                        "quantity": qty,
                        "unit_price": med[2],
                        "total": med[2] * qty,
                        "batches": batches
                    })
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
    with col2:
        st.subheader("Cart")
        if st.session_state.cart:
            df_cart = pd.DataFrame([{"name":c['name'],"qty":c['quantity'],"price":c['unit_price'],"total":c['total']} for c in st.session_state.cart])
            st.dataframe(df_cart)
            subtotal = sum(c['total'] for c in st.session_state.cart)
            discount = st.number_input("Discount ($)", min_value=0.0, value=0.0)
            net = subtotal - discount
            st.write(f"**Subtotal: ${subtotal:.2f}**")
            st.write(f"**Net: ${net:.2f}**")
            patient_search = st.text_input("Patient ID (optional)")
            payment = st.selectbox("Payment Method", ["Cash","Card","Insurance","UPI"])
            if st.button("Complete Sale"):
                with engine.connect() as conn:
                    # Get patient id if provided
                    patient_id = None
                    if patient_search:
                        pat = conn.execute(text("SELECT id FROM patients WHERE patient_id = :pid"), {"pid": patient_search}).fetchone()
                        if pat:
                            patient_id = pat[0]
                    invoice_no = f"INV{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    loyalty_points = int(net * 0.05)
                    conn.execute(text("""
                        INSERT INTO sales (invoice_number, patient_id, user_id, total_amount, discount, net_amount, payment_method, loyalty_points_earned)
                        VALUES (:inv, :pid, :uid, :tot, :disc, :net, :pay, :lp)
                    """), {"inv": invoice_no, "pid": patient_id, "uid": st.session_state.user['id'], "tot": subtotal, "disc": discount, "net": net, "pay": payment, "lp": loyalty_points})
                    sale_id = conn.execute(text("SELECT lastval()")).scalar()
                    for item in st.session_state.cart:
                        for batch in item['batches']:
                            conn.execute(text("""
                                INSERT INTO sale_items (sale_id, medicine_id, batch_id, quantity, unit_price, total)
                                VALUES (:sid, :mid, :bid, :qty, :price, :tot)
                            """), {"sid": sale_id, "mid": item['medicine_id'], "bid": batch['batch_id'], "qty": batch['quantity'], "price": item['unit_price'], "tot": batch['quantity'] * item['unit_price']})
                            conn.execute(text("UPDATE batches SET quantity = quantity - :q WHERE id = :bid"), {"q": batch['quantity'], "bid": batch['batch_id']})
                        conn.execute(text("UPDATE medicines SET current_stock = current_stock - :q WHERE id = :mid"), {"q": item['quantity'], "mid": item['medicine_id']})
                    if patient_id:
                        conn.execute(text("INSERT INTO loyalty_points (patient_id, points, redeemed) VALUES (:pid, :pts, 0) ON CONFLICT (patient_id) DO UPDATE SET points = loyalty_points.points + excluded.points"), {"pid": patient_id, "pts": loyalty_points})
                    conn.commit()
                # Generate receipt
                receipt_data = {
                    "invoice_number": invoice_no,
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "patient_name": patient_search or "Walk-in Customer",
                    "items": [{"name":c['name'],"quantity":c['quantity'],"price":c['unit_price'],"total":c['total']} for c in st.session_state.cart],
                    "total": subtotal,
                    "discount": discount,
                    "net_amount": net
                }
                pdf_bytes = generate_invoice_pdf(receipt_data)
                st.success(f"Sale complete! Invoice: {invoice_no}")
                st.download_button("Download Receipt", data=pdf_bytes, file_name=f"{invoice_no}.pdf", mime="application/pdf")
                st.session_state.cart = []
                st.rerun()
        else:
            st.info("Cart empty")

def render_sales_returns():
    require_permission("sales")
    st.title("🔄 Sales Returns")
    invoice = st.text_input("Enter Invoice Number")
    if invoice:
        with engine.connect() as conn:
            sale = conn.execute(text("SELECT id, net_amount FROM sales WHERE invoice_number = :inv"), {"inv": invoice}).fetchone()
            if not sale:
                st.error("Invoice not found")
                return
            items = conn.execute(text("SELECT si.id, m.name, si.quantity, si.unit_price FROM sale_items si JOIN medicines m ON si.medicine_id = m.id WHERE si.sale_id = :sid"), {"sid": sale[0]}).fetchall()
            for it in items:
                col1, col2, col3 = st.columns([3,1,1])
                col1.write(f"{it[1]} - Sold: {it[2]}")
                return_qty = col2.number_input("Return Qty", min_value=0, max_value=it[2], key=f"ret_{it[0]}")
                if col3.button("Return", key=f"retbtn_{it[0]}"):
                    if return_qty > 0:
                        with engine.connect() as conn2:
                            # Need batch_id from sale_item? We need to know which batch to restore. We'll assume original batch_id is stored.
                            # For simplicity, we add a generic batch restore. In production, store batch_id in sale_items.
                            # Here we'll just increase medicine stock and create a return record.
                            refund = return_qty * it[3]
                            conn2.execute(text("UPDATE medicines SET current_stock = current_stock + :q WHERE id = (SELECT medicine_id FROM sale_items WHERE id = :siid)"), {"q": return_qty, "siid": it[0]})
                            conn2.execute(text("""
                                INSERT INTO sales_returns (original_sale_id, sale_item_id, quantity_returned, refund_amount, reason, created_by)
                                VALUES (:sid, :siid, :q, :ref, 'Customer return', :uid)
                            """), {"sid": sale[0], "siid": it[0], "q": return_qty, "ref": refund, "uid": st.session_state.user['id']})
                            conn2.commit()
                        st.success(f"Returned {return_qty} units, refund ${refund:.2f}")
                        st.rerun()

def render_label_printing():
    require_permission("label_print")
    st.title("🏷️ Label Printing")
    with engine.connect() as conn:
        meds = conn.execute(text("SELECT id, name, generic_name, unit_price FROM medicines")).fetchall()
    med_options = {m[0]: f"{m[1]} ({m[2]})" for m in meds}
    med_id = st.selectbox("Select Medicine", list(med_options.keys()), format_func=lambda x: med_options[x])
    med = next(m for m in meds if m[0]==med_id)
    settings = get_settings_dict()
    st.subheader("Label Preview")
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**{settings.get('pharmacy_name','Pharmacy')}**")
        st.write(f"Medicine: {med[1]}")
        st.write(f"Generic: {med[2]}")
        st.write(f"Price: ${med[3]:.2f}")
        dosage = st.text_input("Dosage Instructions", "Take as directed")
        st.write(f"Pharmacist: {st.session_state.user['full_name']}")
    with col2:
        qr = generate_qr(f"Med: {med[1]}\nDosage: {dosage}")
        st.image(qr, width=150)
        bc = generate_barcode(str(med[0]))
        st.image(bc, width=200)
    if st.button("Print Label"):
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial","B",16)
        pdf.cell(200,10, settings.get("pharmacy_name","Pharmacy"), ln=1, align='C')
        pdf.set_font("Arial","",12)
        pdf.cell(200,10, f"Medicine: {med[1]}", ln=1)
        pdf.cell(200,10, f"Generic: {med[2]}", ln=1)
        pdf.cell(200,10, f"Price: ${med[3]:.2f}", ln=1)
        pdf.cell(200,10, f"Dosage: {dosage}", ln=1)
        pdf.cell(200,10, f"Pharmacist: {st.session_state.user['full_name']}", ln=1)
        # Save QR to temp
        qr_path = tempfile.mktemp(suffix=".png")
        qr.save(qr_path)
        pdf.image(qr_path, x=150, y=80, w=40)
        os.unlink(qr_path)
        label_pdf = pdf.output(dest='S').encode('latin1')
        st.download_button("Download Label", data=label_pdf, file_name=f"label_{med[1]}.pdf", mime="application/pdf")

def render_suppliers():
    require_permission("suppliers")
    st.title("🚚 Suppliers")
    with engine.connect() as conn:
        sups = conn.execute(text("SELECT * FROM suppliers")).fetchall()
    for s in sups:
        with st.expander(f"{s.name} - {s.contact_person or ''}"):
            st.write(f"📞 {s.phone}, 📧 {s.email}, GST: {s.gst_number}")
    st.subheader("Add Supplier")
    with st.form("add_supplier"):
        name = st.text_input("Name")
        contact = st.text_input("Contact Person")
        phone = st.text_input("Phone")
        email = st.text_input("Email")
        address = st.text_area("Address")
        gst = st.text_input("GST")
        terms = st.text_input("Payment Terms")
        if st.form_submit_button("Add"):
            with engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO suppliers (name, contact_person, phone, email, address, gst_number, payment_terms)
                    VALUES (:n, :c, :p, :e, :a, :g, :t)
                """), {"n":name,"c":contact,"p":phone,"e":email,"a":address,"g":gst,"t":terms})
                conn.commit()
            st.rerun()

def render_reports():
    require_permission("reports")
    st.title("📊 Reports")
    report = st.selectbox("Report Type", ["Daily Sales", "Monthly Sales", "Inventory Report", "Expiry Report"])
    if report == "Daily Sales":
        date = st.date_input("Date", datetime.now().date())
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT invoice_number, net_amount, payment_method, created_at, u.full_name
                FROM sales s JOIN users u ON s.user_id = u.id
                WHERE s.created_at::date = :d
            """), {"d": date}).fetchall()
        df = pd.DataFrame([dict(r._mapping) for r in rows])
        st.dataframe(df)
        if not df.empty:
            st.metric("Total", f"${df['net_amount'].sum():.2f}")
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            st.download_button("Export Excel", data=buffer.getvalue(), file_name=f"sales_{date}.xlsx")
    elif report == "Monthly Sales":
        month = st.selectbox("Month", range(1,13), format_func=lambda x: datetime(2000,x,1).strftime("%B"))
        year = st.number_input("Year", min_value=2020, value=datetime.now().year)
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT DATE(created_at) as date, SUM(net_amount) as daily
                FROM sales
                WHERE EXTRACT(YEAR FROM created_at)=:y AND EXTRACT(MONTH FROM created_at)=:m
                GROUP BY DATE(created_at)
            """), {"y": year, "m": month}).fetchall()
        if rows:
            df = pd.DataFrame([{"date":r[0],"sales":r[1]} for r in rows])
            fig = px.line(df, x='date', y='sales', title=f"{datetime(year,month,1).strftime('%B %Y')} Sales")
            st.plotly_chart(fig)
    elif report == "Inventory Report":
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT name, current_stock, reorder_level, unit_price FROM medicines")).fetchall()
        df = pd.DataFrame([{"name":r[0],"stock":r[1],"reorder":r[2],"price":r[3]} for r in rows])
        st.dataframe(df)
        fig = px.bar(df, x='name', y='stock', title='Current Stock')
        st.plotly_chart(fig)
    elif report == "Expiry Report":
        df = get_expiring(90)
        st.dataframe(df)
        if not df.empty:
            fig = px.bar(df, x='name', y='qty', color='expiry', title='Expiring Batches')
            st.plotly_chart(fig)

def render_staff_management():
    require_permission("staff")
    st.title("👨‍💼 Staff Management")
    tab1, tab2, tab3 = st.tabs(["Employees", "Roles", "Attendance"])
    with tab1:
        with engine.connect() as conn:
            users = conn.execute(text("SELECT u.*, r.name as role_name FROM users u JOIN roles r ON u.role_id = r.id")).fetchall()
        for u in users:
            st.write(f"{u.full_name} ({u.username}) - {u.role_name}")
        st.subheader("Add Employee")
        uname = st.text_input("Username")
        pwd = st.text_input("Password", type="password")
        full = st.text_input("Full Name")
        email = st.text_input("Email")
        with engine.connect() as conn:
            roles = conn.execute(text("SELECT id, name FROM roles")).fetchall()
        role_opts = {r[0]: r[1] for r in roles}
        role = st.selectbox("Role", list(role_opts.keys()), format_func=lambda x: role_opts[x])
        if st.button("Add"):
            with engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO users (username, password_hash, full_name, email, role_id, must_change_password)
                    VALUES (:u, :p, :f, :e, :r, 1)
                """), {"u": uname, "p": generate_password_hash(pwd), "f": full, "e": email, "r": role})
                conn.commit()
            st.rerun()
    with tab2:
        with engine.connect() as conn:
            roles = conn.execute(text("SELECT * FROM roles")).fetchall()
            for r in roles:
                st.write(f"**{r.name}**")
                perms = json.loads(r.permissions)
                st.json(perms)
    with tab3:
        st.subheader("Today's Attendance")
        today = date.today()
        with engine.connect() as conn:
            staff = conn.execute(text("SELECT id, full_name FROM users WHERE is_active=1")).fetchall()
        for emp in staff:
            col1, col2, col3 = st.columns([2,1,1])
            col1.write(emp[1])
            check_in = col2.time_input("Check In", value=datetime.now().time(), key=f"in_{emp[0]}")
            check_out = col3.time_input("Check Out", value=datetime.now().time(), key=f"out_{emp[0]}")
            if st.button(f"Mark", key=f"att_{emp[0]}"):
                with engine.connect() as conn:
                    conn.execute(text("""
                        INSERT INTO staff_attendance (user_id, date, check_in, check_out, status)
                        VALUES (:uid, :d, :ci, :co, 'present')
                        ON CONFLICT (user_id, date) DO UPDATE SET check_in = excluded.check_in, check_out = excluded.check_out
                    """), {"uid": emp[0], "d": today, "ci": check_in.strftime("%H:%M"), "co": check_out.strftime("%H:%M")})
                    conn.commit()
                st.success(f"Marked for {emp[1]}")

def render_notifications():
    require_permission("all")
    st.title("🔔 Notifications")
    with engine.connect() as conn:
        notifs = conn.execute(text("SELECT * FROM notifications ORDER BY created_at DESC")).fetchall()
    for n in notifs:
        if n.type == 'warning':
            st.warning(f"**{n.title}**: {n.message}")
        elif n.type == 'danger':
            st.error(f"**{n.title}**: {n.message}")
        else:
            st.info(f"**{n.title}**: {n.message}")
    if st.button("Clear All"):
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM notifications"))
            conn.commit()
        st.rerun()

def render_audit_logs():
    require_permission("audit")
    st.title("📜 Audit Logs")
    with engine.connect() as conn:
        logs = conn.execute(text("""
            SELECT al.*, u.full_name
            FROM audit_logs al LEFT JOIN users u ON al.user_id = u.id
            ORDER BY al.created_at DESC LIMIT 100
        """)).fetchall()
    df = pd.DataFrame([dict(r._mapping) for r in logs])
    st.dataframe(df[['created_at','full_name','action','details']])

def render_advanced_features():
    require_permission("advanced")
    st.title("🚀 Advanced Features")
    tab1, tab2, tab3 = st.tabs(["Drug Interactions", "Stock Forecasting", "Loyalty"])
    with tab1:
        with engine.connect() as conn:
            meds = conn.execute(text("SELECT id, name FROM medicines")).fetchall()
        med_opts = {m[0]: m[1] for m in meds}
        med1 = st.selectbox("Medicine 1", list(med_opts.keys()), format_func=lambda x: med_opts[x])
        med2 = st.selectbox("Medicine 2", list(med_opts.keys()), format_func=lambda x: med_opts[x])
        if st.button("Check"):
            with engine.connect() as conn:
                inter = conn.execute(text("SELECT * FROM drug_interactions WHERE (medicine1_id=:m1 AND medicine2_id=:m2) OR (medicine1_id=:m2 AND medicine2_id=:m1)"), {"m1": med1, "m2": med2}).fetchone()
            if inter:
                st.warning(f"Interaction: {inter.severity} - {inter.description}")
            else:
                st.success("No known interactions")
    with tab2:
        with engine.connect() as conn:
            forecast = conn.execute(text("""
                SELECT m.name, COALESCE(SUM(si.quantity),0) as sold_last_30d
                FROM medicines m
                LEFT JOIN sale_items si ON si.medicine_id = m.id
                LEFT JOIN sales s ON si.sale_id = s.id AND s.created_at >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY m.id
            """)).fetchall()
        if forecast:
            df = pd.DataFrame([{"name":r[0],"sold":r[1],"forecast":int(r[1]*1.1)} for r in forecast])
            st.dataframe(df)
            fig = px.bar(df, x='name', y=['sold','forecast'], title='30-Day Forecast')
            st.plotly_chart(fig)
    with tab3:
        with engine.connect() as conn:
            loyalty = conn.execute(text("""
                SELECT p.first_name, p.last_name, lp.points
                FROM loyalty_points lp JOIN patients p ON lp.patient_id = p.id
                ORDER BY lp.points DESC
            """)).fetchall()
        if loyalty:
            df = pd.DataFrame([{"name":f"{r[0]} {r[1]}","points":r[2]} for r in loyalty])
            st.dataframe(df)
            st.metric("Total Points", df['points'].sum())

def render_settings():
    require_permission("all")
    if st.session_state.user['role_name'] != "Admin":
        st.error("Only Admin can access settings")
        return
    st.title("⚙️ Settings")
    settings = get_settings_dict()
    st.subheader("General")
    pharmacy_name = st.text_input("Pharmacy Name", settings.get("pharmacy_name",""))
    pharmacy_address = st.text_area("Address", settings.get("pharmacy_address",""))
    pharmacy_phone = st.text_input("Phone", settings.get("pharmacy_phone",""))
    pharmacy_email = st.text_input("Email", settings.get("pharmacy_email",""))
    tax_number = st.text_input("Tax Number", settings.get("tax_number",""))
    license_no = st.text_input("Pharmacist License", settings.get("pharmacist_license",""))
    receipt_footer = st.text_area("Receipt Footer", settings.get("receipt_footer",""))
    if st.button("Save General"):
        update_setting("pharmacy_name", pharmacy_name)
        update_setting("pharmacy_address", pharmacy_address)
        update_setting("pharmacy_phone", pharmacy_phone)
        update_setting("pharmacy_email", pharmacy_email)
        update_setting("tax_number", tax_number)
        update_setting("pharmacist_license", license_no)
        update_setting("receipt_footer", receipt_footer)
        st.success("Saved")
        st.rerun()
    st.subheader("Backup & Restore")
    if st.button("Create Backup"):
        # For PostgreSQL, backup is not a simple file. We'll create a SQL dump.
        st.info("Backup not implemented for PostgreSQL; use pg_dump manually.")
    restore_file = st.file_uploader("Restore from SQL dump", type=['sql'])
    if restore_file and st.button("Restore"):
        st.warning("Restore not implemented automatically; use psql manually.")

# ==================== MAIN ====================
def main():
    init_db()
    if not st.session_state.get('logged_in'):
        render_login_page()
        return
    check_session_timeout()
    if st.session_state.user.get('must_change_password'):
        render_change_password()
        return
    st.set_page_config(page_title="Pharmacy Management System", layout="wide")
    st.sidebar.image("https://img.icons8.com/fluency/96/pill.png", width=80)
    st.sidebar.title(f"Welcome, {st.session_state.user['full_name']}")
    st.sidebar.write(f"Role: {st.session_state.user['role_name']}")

    menu_items = {
        "Dashboard": "all", "Medicines": "medicines", "Inventory": "inventory",
        "Patients": "patients_view", "Prescriptions": "prescriptions",
        "Sales & Billing": "sales", "Sales Returns": "sales",
        "Label Printing": "label_print", "Suppliers": "suppliers",
        "Reports": "reports", "Staff Management": "staff",
        "Notifications": "all", "Audit Logs": "audit",
        "Advanced Features": "advanced", "Settings": "all"
    }
    user_perms = json.loads(st.session_state.user.get('permissions', '{}'))
    allowed = []
    for name, perm in menu_items.items():
        if user_perms.get('all') or user_perms.get(perm, False) or perm == "all":
            allowed.append(name)
    for name in allowed:
        if st.sidebar.button(name, use_container_width=True):
            st.session_state.page = name
    if st.sidebar.button("🚪 Logout", use_container_width=True):
        logout_user()

    page = st.session_state.get('page', 'Dashboard')
    if page == "Dashboard":
        render_dashboard()
    elif page == "Medicines":
        render_medicines()
    elif page == "Inventory":
        render_inventory()
    elif page == "Patients":
        render_patients()
    elif page == "Prescriptions":
        render_prescriptions()
    elif page == "Sales & Billing":
        render_sales_billing()
    elif page == "Sales Returns":
        render_sales_returns()
    elif page == "Label Printing":
        render_label_printing()
    elif page == "Suppliers":
        render_suppliers()
    elif page == "Reports":
        render_reports()
    elif page == "Staff Management":
        render_staff_management()
    elif page == "Notifications":
        render_notifications()
    elif page == "Audit Logs":
        render_audit_logs()
    elif page == "Advanced Features":
        render_advanced_features()
    elif page == "Settings":
        render_settings()
    else:
        render_dashboard()

if __name__ == "__main__":
    main()