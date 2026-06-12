#!/usr/bin/env python
"""
PHARMACY MANAGEMENT SYSTEM
Copyright © Isaac Madungwe 2026-2030
All rights reserved.

Run: streamlit run pharmacy_system.py
"""

import os
import re
import json
import io
import tempfile
import shutil
import sqlite3
import logging
from datetime import datetime, timedelta, date
from typing import Dict, Optional, List
import numpy as np

# ==================== DEPENDENCY CHECK ====================
try:
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
except ImportError as e:
    st.error(f"Missing required library: {e}")
    st.info("Run: pip install streamlit pandas bcrypt plotly fpdf qrcode python-barcode Pillow werkzeug numpy openpyxl")
    st.stop()

# ==================== CONFIGURATION ====================
DB_PATH = "pharmacy_management.db"
SESSION_TIMEOUT_SECONDS = 3600
LOGIN_ATTEMPT_LIMIT = 5
LOGIN_LOCKOUT_SECONDS = 300

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@123456")
RESET_SECRET = os.environ.get("RESET_SECRET", "reset123")
UNLOCK_SECRET = os.environ.get("UNLOCK_SECRET", "unlock123")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== DATABASE ====================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn

def clear_all_lockouts():
    with get_db_connection() as conn:
        conn.execute("DELETE FROM settings WHERE key LIKE 'lockout_%' OR key LIKE 'failures_%'")
        conn.commit()

def init_db():
    with get_db_connection() as conn:
        cur = conn.cursor()
        # ========== TABLES ==========
        # Core tables
        cur.execute("CREATE TABLE IF NOT EXISTS roles (id INTEGER PRIMARY KEY, name TEXT UNIQUE, permissions TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, full_name TEXT, email TEXT, role_id INTEGER, is_active INTEGER DEFAULT 1, must_change_password INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(role_id) REFERENCES roles(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS branches (id INTEGER PRIMARY KEY, name TEXT UNIQUE, address TEXT, phone TEXT, email TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY, name TEXT UNIQUE, description TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS departments (id INTEGER PRIMARY KEY, name TEXT UNIQUE, description TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS manufacturers (id INTEGER PRIMARY KEY, name TEXT UNIQUE, contact_person TEXT, phone TEXT, email TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS drug_forms (id INTEGER PRIMARY KEY, name TEXT UNIQUE)")
        cur.execute("CREATE TABLE IF NOT EXISTS therapeutic_classes (id INTEGER PRIMARY KEY, name TEXT UNIQUE, code TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS medical_aids (id INTEGER PRIMARY KEY, name TEXT UNIQUE, code TEXT, contact_person TEXT, phone TEXT, email TEXT, address TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS suppliers (id INTEGER PRIMARY KEY, name TEXT, contact_person TEXT, phone TEXT, email TEXT, address TEXT, gst_number TEXT, payment_terms TEXT, is_active INTEGER DEFAULT 1)")
        cur.execute("CREATE TABLE IF NOT EXISTS medicines (id INTEGER PRIMARY KEY, name TEXT, generic_name TEXT, category_id INTEGER, department_id INTEGER, manufacturer_id INTEGER, drug_form_id INTEGER, therapeutic_class_id INTEGER, barcode TEXT UNIQUE, supplier_id INTEGER, unit_price REAL, reorder_level INTEGER DEFAULT 10, current_stock INTEGER DEFAULT 0, description TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(category_id) REFERENCES categories(id), FOREIGN KEY(department_id) REFERENCES departments(id), FOREIGN KEY(manufacturer_id) REFERENCES manufacturers(id), FOREIGN KEY(drug_form_id) REFERENCES drug_forms(id), FOREIGN KEY(therapeutic_class_id) REFERENCES therapeutic_classes(id), FOREIGN KEY(supplier_id) REFERENCES suppliers(id))")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_medicines_name ON medicines(name)")
        cur.execute("CREATE TABLE IF NOT EXISTS batches (id INTEGER PRIMARY KEY, medicine_id INTEGER, batch_number TEXT, quantity INTEGER, expiry_date DATE, purchase_price REAL, selling_price REAL, mrp REAL, supplier_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(medicine_id) REFERENCES medicines(id), FOREIGN KEY(supplier_id) REFERENCES suppliers(id))")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_batches_expiry ON batches(expiry_date)")
        cur.execute("CREATE TABLE IF NOT EXISTS inventory_transactions (id INTEGER PRIMARY KEY, medicine_id INTEGER, batch_id INTEGER, transaction_type TEXT, quantity INTEGER, reference_id TEXT, notes TEXT, created_by INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(medicine_id) REFERENCES medicines(id), FOREIGN KEY(batch_id) REFERENCES batches(id), FOREIGN KEY(created_by) REFERENCES users(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS patients (id INTEGER PRIMARY KEY, patient_id TEXT UNIQUE, first_name TEXT, last_name TEXT, date_of_birth DATE, gender TEXT, phone TEXT, email TEXT, address TEXT, medical_aid_id INTEGER, medical_aid_number TEXT, blood_group TEXT, allergies TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(medical_aid_id) REFERENCES medical_aids(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS prescriptions (id INTEGER PRIMARY KEY, prescription_number TEXT UNIQUE, patient_id INTEGER, doctor_name TEXT, prescribed_date DATE, expiry_date DATE, status TEXT DEFAULT 'pending', pharmacist_notes TEXT, approved_by INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(patient_id) REFERENCES patients(id), FOREIGN KEY(approved_by) REFERENCES users(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS prescription_items (id INTEGER PRIMARY KEY, prescription_id INTEGER, medicine_id INTEGER, dosage TEXT, duration TEXT, instructions TEXT, quantity INTEGER, FOREIGN KEY(prescription_id) REFERENCES prescriptions(id), FOREIGN KEY(medicine_id) REFERENCES medicines(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS sales (id INTEGER PRIMARY KEY, invoice_number TEXT UNIQUE, patient_id INTEGER, user_id INTEGER, total_amount REAL, discount REAL DEFAULT 0, tax REAL DEFAULT 0, net_amount REAL, payment_method TEXT, payment_status TEXT DEFAULT 'completed', loyalty_points_earned INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(patient_id) REFERENCES patients(id), FOREIGN KEY(user_id) REFERENCES users(id))")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(created_at)")
        cur.execute("CREATE TABLE IF NOT EXISTS sale_items (id INTEGER PRIMARY KEY, sale_id INTEGER, medicine_id INTEGER, batch_id INTEGER, quantity INTEGER, unit_price REAL, total REAL, FOREIGN KEY(sale_id) REFERENCES sales(id), FOREIGN KEY(medicine_id) REFERENCES medicines(id), FOREIGN KEY(batch_id) REFERENCES batches(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS sales_returns (id INTEGER PRIMARY KEY, original_sale_id INTEGER, sale_item_id INTEGER, quantity_returned INTEGER, refund_amount REAL, reason TEXT, created_by INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(original_sale_id) REFERENCES sales(id), FOREIGN KEY(sale_item_id) REFERENCES sale_items(id), FOREIGN KEY(created_by) REFERENCES users(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS purchase_orders (id INTEGER PRIMARY KEY, po_number TEXT UNIQUE, supplier_id INTEGER, order_date DATE, expected_delivery DATE, total_amount REAL, status TEXT DEFAULT 'pending', created_by INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(supplier_id) REFERENCES suppliers(id), FOREIGN KEY(created_by) REFERENCES users(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS staff_attendance (id INTEGER PRIMARY KEY, user_id INTEGER, date DATE, check_in TIME, check_out TIME, status TEXT DEFAULT 'present', UNIQUE(user_id, date), FOREIGN KEY(user_id) REFERENCES users(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY, title TEXT, message TEXT, type TEXT, is_read INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        cur.execute("CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY, user_id INTEGER, action TEXT, details TEXT, ip_address TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id))")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id)")
        cur.execute("CREATE TABLE IF NOT EXISTS loyalty_points (id INTEGER PRIMARY KEY, patient_id INTEGER UNIQUE, points INTEGER DEFAULT 0, redeemed INTEGER DEFAULT 0, FOREIGN KEY(patient_id) REFERENCES patients(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS appointments (id INTEGER PRIMARY KEY, patient_id INTEGER, appointment_date DATE, appointment_time TIME, purpose TEXT, status TEXT DEFAULT 'scheduled', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(patient_id) REFERENCES patients(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS drug_interactions (id INTEGER PRIMARY KEY, medicine1_id INTEGER, medicine2_id INTEGER, severity TEXT, description TEXT, FOREIGN KEY(medicine1_id) REFERENCES medicines(id), FOREIGN KEY(medicine2_id) REFERENCES medicines(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS stocktakes (id INTEGER PRIMARY KEY, name TEXT, status TEXT DEFAULT 'prepared', prepared_by INTEGER, prepared_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, closed_by INTEGER, closed_at TIMESTAMP, FOREIGN KEY(prepared_by) REFERENCES users(id), FOREIGN KEY(closed_by) REFERENCES users(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS stocktake_items (id INTEGER PRIMARY KEY, stocktake_id INTEGER, medicine_id INTEGER, expected_quantity INTEGER, counted_quantity INTEGER, variance INTEGER, FOREIGN KEY(stocktake_id) REFERENCES stocktakes(id), FOREIGN KEY(medicine_id) REFERENCES medicines(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS system_settings (id INTEGER PRIMARY KEY, key TEXT UNIQUE, value TEXT, description TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS till_sessions (id INTEGER PRIMARY KEY, user_id INTEGER, opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, closed_at TIMESTAMP, opening_balance REAL DEFAULT 0, closing_balance REAL, cash_sales REAL DEFAULT 0, card_sales REAL DEFAULT 0, medical_aid_sales REAL DEFAULT 0, status TEXT DEFAULT 'open', FOREIGN KEY(user_id) REFERENCES users(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS quotations (id INTEGER PRIMARY KEY, quotation_no TEXT UNIQUE, patient_id INTEGER, items TEXT, total_amount REAL, valid_until DATE, created_by INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(patient_id) REFERENCES patients(id), FOREIGN KEY(created_by) REFERENCES users(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")

        # ========== DEFAULT DATA ==========
        # Roles
        roles = [
            ("Admin", '{"all":true}'),
            ("Manager", '{"medicines":true,"inventory":true,"suppliers":true,"reports":true,"staff":true,"audit":true}'),
            ("Pharmacist", '{"prescriptions":true,"inventory_view":true,"sales_view":true,"label_print":true}'),
            ("Cashier", '{"sales":true,"patients_view":true}')
        ]
        for name, perms in roles:
            cur.execute("INSERT OR IGNORE INTO roles (name, permissions) VALUES (?,?)", (name, perms))

        # Admin user
        admin_role = cur.execute("SELECT id FROM roles WHERE name='Admin'").fetchone()
        admin_exists = cur.execute("SELECT id FROM users WHERE username='admin'").fetchone()
        if not admin_exists and admin_role:
            cur.execute("INSERT INTO users (username, password_hash, full_name, email, role_id, must_change_password) VALUES (?,?,?,?,?,1)",
                        ("admin", generate_password_hash(ADMIN_PASSWORD), "System Administrator", "admin@pharmacy.com", admin_role[0]))

        # Default categories
        categories = ["Antibiotics","Analgesics","Antipyretics","Vitamins","Antihistamines","Dermatologicals"]
        for cat in categories:
            cur.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat,))

        # Default departments
        default_depts = ["General", "Prescription", "OTC", "Medical Devices"]
        for dept in default_depts:
            cur.execute("INSERT OR IGNORE INTO departments (name) VALUES (?)", (dept,))

        # Default drug forms
        default_forms = ["Tablet", "Capsule", "Syrup", "Injection", "Cream", "Drops"]
        for form in default_forms:
            cur.execute("INSERT OR IGNORE INTO drug_forms (name) VALUES (?)", (form,))

        # Default therapeutic classes
        default_classes = [("Analgesics", "N02"), ("Antibiotics", "J01"), ("Antihypertensives", "C02")]
        for name, code in default_classes:
            cur.execute("INSERT OR IGNORE INTO therapeutic_classes (name, code) VALUES (?,?)", (name, code))

        # Default settings
        default_settings = {
            "pharmacy_name": "HealthPlus Pharmacy",
            "pharmacy_address": "123 Main Street, City",
            "pharmacy_phone": "+1 234 567 8900",
            "pharmacy_email": "info@healthplus.com",
            "tax_number": "TAX123456",
            "pharmacist_license": "PHARM-7890",
            "receipt_footer": "Thank you for your visit!",
            "loyalty_rate": "5",
            "gst_rate": "5"
        }
        for key, val in default_settings.items():
            cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)", (key, val))

        conn.commit()

    # Fix loyalty_points uniqueness
    with get_db_connection() as conn:
        cursor = conn.execute("PRAGMA index_list('loyalty_points')")
        indexes = [row['name'] for row in cursor.fetchall()]
        if not any('sqlite_autoindex_loyalty_points' in idx or 'patient_id' in idx for idx in indexes):
            conn.execute("BEGIN TRANSACTION")
            conn.execute("CREATE TABLE loyalty_points_new (id INTEGER PRIMARY KEY, patient_id INTEGER UNIQUE, points INTEGER DEFAULT 0, redeemed INTEGER DEFAULT 0, FOREIGN KEY(patient_id) REFERENCES patients(id))")
            conn.execute("INSERT INTO loyalty_points_new (id, patient_id, points, redeemed) SELECT id, patient_id, points, redeemed FROM loyalty_points")
            conn.execute("DROP TABLE loyalty_points")
            conn.execute("ALTER TABLE loyalty_points_new RENAME TO loyalty_points")
            conn.commit()

init_db()
clear_all_lockouts()

# ==================== HELPER FUNCTIONS ====================
def get_settings_dict():
    try:
        with get_db_connection() as conn:
            return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings").fetchall()}
    except Exception as e:
        logger.error(f"Failed to get settings: {e}")
        return {}

def update_setting(key, value):
    try:
        with get_db_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?,?,CURRENT_TIMESTAMP)", (key, value))
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to update setting {key}: {e}")
        st.error("Could not save setting. Please try again.")

def log_audit(user_id, action, details=""):
    try:
        with get_db_connection() as conn:
            conn.execute("INSERT INTO audit_logs (user_id, action, details) VALUES (?,?,?)", (user_id, action, details))
            conn.commit()
    except Exception as e:
        logger.error(f"Audit log failed: {e}")

def require_permission(perm):
    if not st.session_state.get('logged_in'):
        st.error("Please log in.")
        st.stop()
    perms = json.loads(st.session_state.user.get('permissions', '{}'))
    if perms.get('all') or perms.get(perm):
        return True
    st.error(f"Permission '{perm}' required. Access denied.")
    st.stop()

def get_low_stock():
    try:
        with get_db_connection() as conn:
            rows = conn.execute("SELECT id,name,current_stock,reorder_level FROM medicines WHERE current_stock <= reorder_level").fetchall()
            return pd.DataFrame([{"id":r[0],"name":r[1],"stock":r[2],"reorder":r[3]} for r in rows])
    except Exception as e:
        logger.error(f"Low stock query error: {e}")
        return pd.DataFrame()

def get_expiring(days=30):
    exp = (datetime.now() + timedelta(days=days)).date().isoformat()
    try:
        with get_db_connection() as conn:
            rows = conn.execute("SELECT b.id, m.name, b.batch_number, b.expiry_date, b.quantity FROM batches b JOIN medicines m ON b.medicine_id=m.id WHERE b.expiry_date <= ? AND b.quantity>0 ORDER BY b.expiry_date", (exp,)).fetchall()
            return pd.DataFrame([{"id":r[0],"name":r[1],"batch":r[2],"expiry":r[3],"qty":r[4]} for r in rows])
    except Exception as e:
        logger.error(f"Expiry query error: {e}")
        return pd.DataFrame()

def get_best_batch(medicine_id, needed):
    try:
        with get_db_connection() as conn:
            batches = conn.execute("SELECT id, quantity, selling_price FROM batches WHERE medicine_id=? AND quantity>0 AND expiry_date>date('now') ORDER BY expiry_date ASC", (medicine_id,)).fetchall()
        res = []
        rem = needed
        for b in batches:
            take = min(b[1], rem)
            if take > 0:
                res.append({"batch_id": b[0], "quantity": take, "price": b[2]})
                rem -= take
            if rem == 0:
                break
        if rem > 0:
            raise ValueError("Insufficient stock")
        return res
    except Exception as e:
        logger.error(f"Batch selection error: {e}")
        raise ValueError("Error selecting batches. Check stock or contact support.")

def generate_invoice_pdf(data):
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", "B", 16)
        s = get_settings_dict()
        pdf.cell(200, 10, s.get("pharmacy_name", "Pharmacy"), ln=1, align='C')
        pdf.set_font("Arial", "", 10)
        pdf.cell(200, 5, s.get("pharmacy_address", ""), ln=1, align='C')
        pdf.cell(200, 5, f"Phone: {s.get('pharmacy_phone', '')}", ln=1, align='C')
        pdf.ln(10)
        pdf.set_font("Arial", "B", 12)
        pdf.cell(200, 10, f"Invoice: {data['invoice_number']}", ln=1)
        pdf.cell(200, 10, f"Date: {data['date']}", ln=1)
        pdf.cell(200, 10, f"Patient: {data.get('patient_name', 'Walk-in')}", ln=1)
        pdf.ln(5)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(80, 10, "Item", 1)
        pdf.cell(30, 10, "Qty", 1)
        pdf.cell(40, 10, "Price", 1)
        pdf.cell(40, 10, "Total", 1)
        pdf.ln()
        pdf.set_font("Arial", "", 10)
        for it in data['items']:
            pdf.cell(80, 10, it['name'][:30], 1)
            pdf.cell(30, 10, str(it['quantity']), 1)
            pdf.cell(40, 10, f"${it['price']:.2f}", 1)
            pdf.cell(40, 10, f"${it['total']:.2f}", 1)
            pdf.ln()
        pdf.ln(5)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(150, 10, "Total:", 0)
        pdf.cell(40, 10, f"${data['total']:.2f}", 0)
        pdf.ln()
        pdf.cell(150, 10, "Discount:", 0)
        pdf.cell(40, 10, f"${data.get('discount', 0):.2f}", 0)
        pdf.ln()
        pdf.cell(150, 10, "Tax (GST):", 0)
        pdf.cell(40, 10, f"${data.get('tax', 0):.2f}", 0)
        pdf.ln()
        pdf.cell(150, 10, "Net Amount:", 0)
        pdf.cell(40, 10, f"${data['net_amount']:.2f}", 0)
        pdf.ln(10)
        pdf.cell(200, 10, s.get("receipt_footer", "Thank you!"), ln=1, align='C')
        return pdf.output(dest='S').encode('latin1')
    except Exception as e:
        logger.error(f"PDF generation error: {e}")
        st.error("Failed to generate PDF. Please try again.")
        return b""

def generate_barcode(data):
    try:
        code128 = barcode.get_barcode_class('code128')
        buf = io.BytesIO()
        code128(data, writer=ImageWriter()).write(buf)
        buf.seek(0)
        return Image.open(buf)
    except Exception as e:
        logger.error(f"Barcode error: {e}")
        return Image.new('RGB', (300, 100), 'white')

def generate_qr(data):
    qr = qrcode.QRCode(box_size=5, border=2)
    qr.add_data(data)
    return qr.make_image(fill_color="black", back_color="white")

def create_notification(title, message, type_="info"):
    try:
        with get_db_connection() as conn:
            conn.execute("INSERT INTO notifications (title, message, type) VALUES (?,?,?)", (title, message, type_))
            conn.commit()
    except Exception as e:
        logger.error(f"Notification creation error: {e}")

def stock_forecast(medicine_id, days=30):
    try:
        with get_db_connection() as conn:
            rows = conn.execute("""
                SELECT DATE(created_at) as d, SUM(si.quantity) as qty
                FROM sale_items si JOIN sales s ON si.sale_id=s.id
                WHERE si.medicine_id=? AND s.created_at >= date('now','-30 days')
                GROUP BY DATE(s.created_at)
            """, (medicine_id,)).fetchall()
        if len(rows) < 2:
            return None
        x = list(range(len(rows)))
        y = [r[1] for r in rows]
        z = np.polyfit(x, y, 1)
        forecast = z[0] * days + z[1]
        return max(0, int(forecast))
    except Exception as e:
        logger.error(f"Forecast error: {e}")
        return None

def usage_analytics(medicine_id=None, days=30):
    try:
        with get_db_connection() as conn:
            if medicine_id:
                rows = conn.execute("""
                    SELECT DATE(s.created_at) as date, SUM(si.quantity) as qty
                    FROM sale_items si JOIN sales s ON si.sale_id=s.id
                    WHERE si.medicine_id=? AND s.created_at >= date('now', ?)
                    GROUP BY DATE(s.created_at)
                    ORDER BY date
                """, (medicine_id, f'-{days} days')).fetchall()
            else:
                rows = conn.execute("""
                    SELECT DATE(s.created_at) as date, SUM(si.quantity) as qty
                    FROM sale_items si JOIN sales s ON si.sale_id=s.id
                    WHERE s.created_at >= date('now', ?)
                    GROUP BY DATE(s.created_at)
                    ORDER BY date
                """, (f'-{days} days',)).fetchall()
        return pd.DataFrame([{"date": r[0], "quantity": r[1]} for r in rows])
    except Exception as e:
        logger.error(f"Usage analytics error: {e}")
        return pd.DataFrame()

def auto_create_purchase_orders():
    low = get_low_stock()
    if low.empty:
        return 0
    created = 0
    with get_db_connection() as conn:
        for _, med in low.iterrows():
            supplier = conn.execute("SELECT id FROM suppliers WHERE is_active=1 LIMIT 1").fetchone()
            if supplier:
                po_num = f"POAUTO{datetime.now().strftime('%Y%m%d%H%M%S')}_{med['id']}"
                conn.execute("""
                    INSERT INTO purchase_orders (po_number, supplier_id, order_date, expected_delivery, total_amount, status, created_by, created_at)
                    VALUES (?, ?, date('now'), date('now', '+7 days'), ?, 'pending', ?, CURRENT_TIMESTAMP)
                """, (po_num, supplier[0], med['reorder'] * 2, 1))
                created += 1
        conn.commit()
    return created

# ==================== AUTHENTICATION ====================
def login_user(username, password):
    try:
        with get_db_connection() as conn:
            lock_row = conn.execute("SELECT value FROM settings WHERE key = ?", (f"lockout_{username}",)).fetchone()
            if lock_row:
                try:
                    lock_until = datetime.fromisoformat(lock_row[0])
                    if lock_until > datetime.now():
                        st.error("Account locked. Try again later or use ?unlock=unlock123")
                        return None
                    else:
                        conn.execute("DELETE FROM settings WHERE key = ?", (f"lockout_{username}",))
                        conn.commit()
                except Exception:
                    conn.execute("DELETE FROM settings WHERE key = ?", (f"lockout_{username}",))
                    conn.commit()

            user = conn.execute("""
                SELECT u.id, u.username, u.password_hash, u.full_name, u.email,
                       u.role_id, u.must_change_password,
                       r.name as role_name, r.permissions
                FROM users u
                JOIN roles r ON u.role_id = r.id
                WHERE u.username = ? AND u.is_active = 1
            """, (username,)).fetchone()

            if user and check_password_hash(user[2], password):
                conn.execute("DELETE FROM settings WHERE key = ?", (f"failures_{username}",))
                conn.execute("DELETE FROM settings WHERE key = ?", (f"lockout_{username}",))
                conn.commit()
                log_audit(user[0], "LOGIN", f"User {username} logged in")
                return {
                    "id": user[0],
                    "username": user[1],
                    "full_name": user[3],
                    "email": user[4],
                    "role_id": user[5],
                    "must_change_password": user[6],
                    "role_name": user[7],
                    "permissions": user[8]
                }
            else:
                fail_row = conn.execute("SELECT value FROM settings WHERE key = ?", (f"failures_{username}",)).fetchone()
                fail_count = int(fail_row[0]) if fail_row else 0
                fail_count += 1
                conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (f"failures_{username}", str(fail_count)))
                if fail_count >= LOGIN_ATTEMPT_LIMIT:
                    lock_until = (datetime.now() + timedelta(seconds=LOGIN_LOCKOUT_SECONDS)).isoformat()
                    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (f"lockout_{username}", lock_until))
                    conn.commit()
                    st.error(f"Too many failed attempts. Account locked for {LOGIN_LOCKOUT_SECONDS} seconds.")
                else:
                    conn.commit()
                    st.error(f"Invalid credentials. {LOGIN_ATTEMPT_LIMIT - fail_count} attempts remaining.")
                return None
    except Exception as e:
        logger.error(f"Login error: {e}")
        st.error("System error during login. Please try again.")
        return None

def change_password(user_id, new_password):
    if len(new_password) < 8 or not re.search(r"[A-Z]", new_password) or not re.search(r"[a-z]", new_password) or not re.search(r"[0-9]", new_password):
        raise ValueError("Password must be at least 8 characters with uppercase, lowercase, and digit.")
    try:
        with get_db_connection() as conn:
            conn.execute("UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?", (generate_password_hash(new_password), user_id))
            conn.commit()
            log_audit(user_id, "PASSWORD_CHANGE", "")
    except Exception as e:
        logger.error(f"Password change error: {e}")
        raise ValueError("Database error during password change.")

def logout_user():
    if st.session_state.get('user'):
        log_audit(st.session_state.user['id'], "LOGOUT", "")
    keys_to_clear = ['logged_in', 'user', 'login_time', 'must_change_password', 'page', 'cart', 'pres_items', 'ai_msgs', 'edit_medicine']
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()

def check_session_timeout():
    if 'login_time' in st.session_state:
        if (datetime.now() - st.session_state.login_time).total_seconds() > SESSION_TIMEOUT_SECONDS:
            st.warning("Session expired due to inactivity.")
            logout_user()
            st.stop()
    else:
        st.session_state.login_time = datetime.now()

# ==================== AI ASSISTANT ====================
MED_KNOWLEDGE = {
    "fever": {"meds": ["Paracetamol", "Ibuprofen"], "dosage": "500mg every 6h", "warning": "Max 4g/day"},
    "cold": {"meds": ["Cetirizine", "Pseudoephedrine"], "dosage": "10mg daily", "warning": "May cause drowsiness"},
    "cough": {"meds": ["Dextromethorphan", "Guaifenesin"], "dosage": "10-20mg every 4h", "warning": "Drink water"},
    "headache": {"meds": ["Aspirin", "Ibuprofen"], "dosage": "400mg every 6h", "warning": "Take with food"},
    "diarrhea": {"meds": ["Loperamide", "ORS"], "dosage": "2mg after each loose stool", "warning": "Stay hydrated"},
    "nausea": {"meds": ["Ondansetron", "Domperidone"], "dosage": "4-8mg every 8h", "warning": "May cause drowsiness"},
    "infection": {"meds": ["Amoxicillin", "Ciprofloxacin"], "dosage": "500mg twice daily", "warning": "Complete full course"},
    "allergy": {"meds": ["Loratadine", "Fexofenadine"], "dosage": "10mg daily", "warning": "Avoid alcohol"},
    "diabetes": {"meds": ["Metformin", "Insulin"], "dosage": "500mg twice daily", "warning": "Monitor blood sugar"},
    "hypertension": {"meds": ["Lisinopril", "Amlodipine"], "dosage": "10mg once daily", "warning": "Check BP regularly"},
    "asthma": {"meds": ["Salbutamol", "Budesonide"], "dosage": "2 puffs as needed", "warning": "Rinse mouth after use"},
}

def ai_response(q):
    q = q.lower()
    if "stock" in q or "available" in q:
        try:
            with get_db_connection() as conn:
                meds = conn.execute("SELECT name, current_stock FROM medicines WHERE current_stock>0 LIMIT 5").fetchall()
            if meds:
                return "📦 Stock:\n" + "\n".join([f"{m[0]}: {m[1]} units" for m in meds])
            else:
                return "No medicines in stock."
        except:
            return "Unable to fetch stock at the moment."
    if "expiring" in q:
        exp = get_expiring(30)
        if not exp.empty:
            return "⚠️ Expiring soon:\n" + "\n".join([f"{r['name']} (batch {r['batch']}) expires {r['expiry']}" for _, r in exp.iterrows()])
        else:
            return "No products expiring within 30 days."
    if "low stock" in q:
        low = get_low_stock()
        if not low.empty:
            return "⚠️ Low stock:\n" + "\n".join([f"{r['name']}: {r['stock']} units (reorder level {r['reorder']})" for _, r in low.iterrows()])
        else:
            return "All stock levels are adequate."
    for sym, info in MED_KNOWLEDGE.items():
        if sym in q:
            return (f"🩺 For {sym}:\n- Medicines: {', '.join(info['meds'])}\n"
                    f"- Dosage: {info['dosage']}\n- Warning: {info['warning']}\n\n*Consult a doctor before use.*")
    if "help" in q:
        return ("🤖 **AI Assistant Help**\n"
                "- Ask about symptoms: 'fever', 'cold', 'headache', 'diarrhea', 'nausea', 'infection'\n"
                "- Check stock: 'stock available', 'low stock alerts'\n"
                "- Expiry alerts: 'expiring medicines'\n"
                "- Drug interactions: 'interaction between X and Y'\n"
                "- Or just ask any pharmacy-related question!")
    return "I can help with medicine suggestions, stock status, expiring products, and more. Try 'fever', 'low stock', or 'expiring medicines'."

# ==================== PAGE FUNCTIONS ====================
# We will implement each page function step by step.
# Due to length, we'll include all necessary render_* functions.
# All functions are based on the previous working versions, extended with new modules.

def render_dashboard():
    require_permission("all")
    st.title("📊 Dashboard")
    with get_db_connection() as conn:
        total_meds = conn.execute("SELECT COUNT(*) FROM medicines").fetchone()[0]
        total_patients = conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
        today_sales = conn.execute("SELECT COALESCE(SUM(net_amount),0) FROM sales WHERE DATE(created_at)=DATE('now')").fetchone()[0]
        month_sales = conn.execute("SELECT COALESCE(SUM(net_amount),0) FROM sales WHERE strftime('%Y-%m',created_at)=strftime('%Y-%m','now')").fetchone()[0]
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

    with get_db_connection() as conn:
        trend = conn.execute("""
            SELECT DATE(created_at) as d, SUM(net_amount) as s
            FROM sales
            WHERE created_at >= DATE('now','-7 days')
            GROUP BY DATE(created_at) ORDER BY d
        """).fetchall()
    if trend:
        df = pd.DataFrame([{"date": r[0], "sales": r[1]} for r in trend])
        fig = px.line(df, x='date', y='sales', title='Last 7 Days Sales')
        st.plotly_chart(fig, use_container_width=True)

    with get_db_connection() as conn:
        top = conn.execute("""
            SELECT m.name, SUM(si.quantity) as sold
            FROM sale_items si
            JOIN medicines m ON si.medicine_id = m.id
            GROUP BY si.medicine_id
            ORDER BY sold DESC LIMIT 5
        """).fetchall()
    if top:
        df_top = pd.DataFrame([{"name": r[0], "sold": r[1]} for r in top])
        fig2 = px.bar(df_top, x='name', y='sold', title='Top Selling Medicines')
        st.plotly_chart(fig2, use_container_width=True)

def render_medicines():
    require_permission("medicines")
    st.title("💊 Medicines Management")
    tab1, tab2, tab3 = st.tabs(["List", "Add/Edit", "Categories", "Departments", "Manufacturers", "Drug Forms", "Therapeutic Classes"])
    with tab1:
        search = st.text_input("Search")
        page = st.number_input("Page", min_value=1, value=1, step=1)
        per = 20
        off = (page-1)*per
        with get_db_connection() as conn:
            if search:
                count = conn.execute("SELECT COUNT(*) FROM medicines WHERE name LIKE ? OR generic_name LIKE ?", (f"%{search}%", f"%{search}%")).fetchone()[0]
                rows = conn.execute("""
                    SELECT m.*, c.name as cat, d.name as dept, man.name as manu, df.name as form, tc.name as tclass
                    FROM medicines m
                    LEFT JOIN categories c ON m.category_id = c.id
                    LEFT JOIN departments d ON m.department_id = d.id
                    LEFT JOIN manufacturers man ON m.manufacturer_id = man.id
                    LEFT JOIN drug_forms df ON m.drug_form_id = df.id
                    LEFT JOIN therapeutic_classes tc ON m.therapeutic_class_id = tc.id
                    WHERE m.name LIKE ? OR m.generic_name LIKE ?
                    LIMIT ? OFFSET ?
                """, (f"%{search}%", f"%{search}%", per, off)).fetchall()
            else:
                count = conn.execute("SELECT COUNT(*) FROM medicines").fetchone()[0]
                rows = conn.execute("""
                    SELECT m.*, c.name as cat, d.name as dept, man.name as manu, df.name as form, tc.name as tclass
                    FROM medicines m
                    LEFT JOIN categories c ON m.category_id = c.id
                    LEFT JOIN departments d ON m.department_id = d.id
                    LEFT JOIN manufacturers man ON m.manufacturer_id = man.id
                    LEFT JOIN drug_forms df ON m.drug_form_id = df.id
                    LEFT JOIN therapeutic_classes tc ON m.therapeutic_class_id = tc.id
                    LIMIT ? OFFSET ?
                """, (per, off)).fetchall()
        st.write(f"Total: {count}")
        for r in rows:
            col1, col2, col3, col4 = st.columns([3,1,1,1])
            col1.write(f"**{r['name']}** (Stock: {r['current_stock']})")
            if col2.button("✏️", key=f"edit_{r['id']}"):
                st.session_state.edit_medicine = dict(r)
                st.success("Medicine loaded for editing")
            if col3.button("🗑️", key=f"del_{r['id']}"):
                with get_db_connection() as conn2:
                    conn2.execute("DELETE FROM medicines WHERE id=?", (r['id'],))
                    conn2.commit()
                st.success(f"Medicine '{r['name']}' deleted")
                st.rerun()
            if col4.button("🏷️", key=f"barcode_{r['id']}"):
                img = generate_barcode(r['barcode'] or str(r['id']))
                st.image(img, width=100)

    with tab2:
        med = st.session_state.get('edit_medicine', {})
        # Fetch all lookup data
        with get_db_connection() as conn:
            cats = conn.execute("SELECT id, name FROM categories").fetchall()
            depts = conn.execute("SELECT id, name FROM departments").fetchall()
            mans = conn.execute("SELECT id, name FROM manufacturers").fetchall()
            forms = conn.execute("SELECT id, name FROM drug_forms").fetchall()
            tclasses = conn.execute("SELECT id, name FROM therapeutic_classes").fetchall()
            supps = conn.execute("SELECT id, name FROM suppliers").fetchall()
        cat_opts = {c[0]: c[1] for c in cats}
        dept_opts = {d[0]: d[1] for d in depts}
        man_opts = {m[0]: m[1] for m in mans}
        form_opts = {f[0]: f[1] for f in forms}
        tc_opts = {tc[0]: tc[1] for tc in tclasses}
        supp_opts = {s[0]: s[1] for s in supps}

        name = st.text_input("Medicine Name", med.get('name', ''))
        generic = st.text_input("Generic Name", med.get('generic_name', ''))
        category = st.selectbox("Category", list(cat_opts.keys()), format_func=lambda x: cat_opts[x], index=0 if not med else next((i for i,c in enumerate(cats) if c[0]==med.get('category_id')),0))
        department = st.selectbox("Department", list(dept_opts.keys()), format_func=lambda x: dept_opts[x], index=0 if not med else next((i for i,d in enumerate(depts) if d[0]==med.get('department_id')),0))
        manufacturer = st.selectbox("Manufacturer", list(man_opts.keys()), format_func=lambda x: man_opts[x], index=0 if not med else next((i for i,m in enumerate(mans) if m[0]==med.get('manufacturer_id')),0))
        drug_form = st.selectbox("Drug Form", list(form_opts.keys()), format_func=lambda x: form_opts[x], index=0 if not med else next((i for i,f in enumerate(forms) if f[0]==med.get('drug_form_id')),0))
        therapeutic_class = st.selectbox("Therapeutic Class", list(tc_opts.keys()), format_func=lambda x: tc_opts[x], index=0 if not med else next((i for i,tc in enumerate(tclasses) if tc[0]==med.get('therapeutic_class_id')),0))
        bcode = st.text_input("Barcode", med.get('barcode', ''))
        supplier = st.selectbox("Supplier", list(supp_opts.keys()), format_func=lambda x: supp_opts[x], index=0 if not med else next((i for i,s in enumerate(supps) if s[0]==med.get('supplier_id')),0))
        price = st.number_input("Unit Price ($)", min_value=0.0, value=float(med.get('unit_price', 0)))
        reorder = st.number_input("Reorder Level", min_value=0, value=int(med.get('reorder_level', 10)))
        stock = st.number_input("Current Stock", min_value=0, value=int(med.get('current_stock', 0)))
        desc = st.text_area("Description", med.get('description', ''))
        if st.button("Save Medicine"):
            with get_db_connection() as conn:
                if 'edit_medicine' in st.session_state:
                    conn.execute("""
                        UPDATE medicines
                        SET name=?, generic_name=?, category_id=?, department_id=?, manufacturer_id=?,
                            drug_form_id=?, therapeutic_class_id=?, barcode=?, supplier_id=?,
                            unit_price=?, reorder_level=?, current_stock=?, description=?
                        WHERE id=?
                    """, (name, generic, category, department, manufacturer, drug_form, therapeutic_class, bcode, supplier, price, reorder, stock, desc, med['id']))
                    del st.session_state.edit_medicine
                    st.success("Medicine updated successfully")
                else:
                    conn.execute("""
                        INSERT INTO medicines (name, generic_name, category_id, department_id, manufacturer_id,
                                              drug_form_id, therapeutic_class_id, barcode, supplier_id,
                                              unit_price, reorder_level, current_stock, description)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (name, generic, category, department, manufacturer, drug_form, therapeutic_class, bcode, supplier, price, reorder, stock, desc))
                    st.success("Medicine added successfully")
                conn.commit()
            st.rerun()

    with tab3:
        st.subheader("Categories")
        new_cat = st.text_input("New Category Name")
        if st.button("Add Category") and new_cat:
            with get_db_connection() as conn:
                conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (new_cat,))
                conn.commit()
            st.success(f"Category '{new_cat}' added")
            st.rerun()
        with get_db_connection() as conn:
            cats = conn.execute("SELECT id, name FROM categories").fetchall()
            for c in cats:
                col1, col2 = st.columns([3,1])
                col1.write(c[1])
                if col2.button("Delete", key=f"delcat_{c[0]}"):
                    conn.execute("DELETE FROM categories WHERE id=?", (c[0],))
                    conn.commit()
                    st.success("Category deleted")
                    st.rerun()

    with tab4:
        st.subheader("Departments")
        new_dept = st.text_input("New Department Name")
        if st.button("Add Department") and new_dept:
            with get_db_connection() as conn:
                conn.execute("INSERT OR IGNORE INTO departments (name) VALUES (?)", (new_dept,))
                conn.commit()
            st.success(f"Department '{new_dept}' added")
            st.rerun()
        with get_db_connection() as conn:
            depts = conn.execute("SELECT id, name FROM departments").fetchall()
            for d in depts:
                col1, col2 = st.columns([3,1])
                col1.write(d[1])
                if col2.button("Delete", key=f"deldept_{d[0]}"):
                    conn.execute("DELETE FROM departments WHERE id=?", (d[0],))
                    conn.commit()
                    st.success("Department deleted")
                    st.rerun()

    with tab5:
        st.subheader("Manufacturers")
        new_man = st.text_input("New Manufacturer Name")
        contact = st.text_input("Contact Person")
        phone = st.text_input("Phone")
        email = st.text_input("Email")
        if st.button("Add Manufacturer") and new_man:
            with get_db_connection() as conn:
                conn.execute("INSERT INTO manufacturers (name, contact_person, phone, email) VALUES (?,?,?,?)", (new_man, contact, phone, email))
                conn.commit()
            st.success(f"Manufacturer '{new_man}' added")
            st.rerun()
        with get_db_connection() as conn:
            mans = conn.execute("SELECT id, name, contact_person, phone, email FROM manufacturers").fetchall()
            for m in mans:
                with st.expander(f"{m[1]}"):
                    st.write(f"Contact: {m[2]}, Phone: {m[3]}, Email: {m[4]}")
                    if st.button("Delete", key=f"delman_{m[0]}"):
                        conn.execute("DELETE FROM manufacturers WHERE id=?", (m[0],))
                        conn.commit()
                        st.rerun()

    with tab6:
        st.subheader("Drug Forms")
        new_form = st.text_input("New Drug Form")
        if st.button("Add Drug Form") and new_form:
            with get_db_connection() as conn:
                conn.execute("INSERT OR IGNORE INTO drug_forms (name) VALUES (?)", (new_form,))
                conn.commit()
            st.success(f"Drug form '{new_form}' added")
            st.rerun()
        with get_db_connection() as conn:
            forms = conn.execute("SELECT id, name FROM drug_forms").fetchall()
            for f in forms:
                col1, col2 = st.columns([3,1])
                col1.write(f[1])
                if col2.button("Delete", key=f"delform_{f[0]}"):
                    conn.execute("DELETE FROM drug_forms WHERE id=?", (f[0],))
                    conn.commit()
                    st.success("Drug form deleted")
                    st.rerun()

    with tab7:
        st.subheader("Therapeutic Classes")
        new_tc = st.text_input("New Therapeutic Class")
        code = st.text_input("Code")
        if st.button("Add Therapeutic Class") and new_tc:
            with get_db_connection() as conn:
                conn.execute("INSERT INTO therapeutic_classes (name, code) VALUES (?,?)", (new_tc, code))
                conn.commit()
            st.success(f"Therapeutic class '{new_tc}' added")
            st.rerun()
        with get_db_connection() as conn:
            tcs = conn.execute("SELECT id, name, code FROM therapeutic_classes").fetchall()
            for tc in tcs:
                col1, col2 = st.columns([3,1])
                col1.write(f"{tc[1]} ({tc[2]})")
                if col2.button("Delete", key=f"deltc_{tc[0]}"):
                    conn.execute("DELETE FROM therapeutic_classes WHERE id=?", (tc[0],))
                    conn.commit()
                    st.success("Therapeutic class deleted")
                    st.rerun()

def render_inventory():
    require_permission("inventory")
    st.title("📦 Inventory Management")
    tab1, tab2, tab3 = st.tabs(["Stock In/Out", "Batches", "Breakages", "Expired Drugs", "Out of Stock", "Price Change"])
    with tab1:
        with get_db_connection() as conn:
            meds = conn.execute("SELECT id, name FROM medicines").fetchall()
        if not meds:
            st.warning("No medicines found. Add medicines first.")
            return
        med_opts = {m[0]: m[1] for m in meds}
        med_id = st.selectbox("Select Medicine", list(med_opts.keys()), format_func=lambda x: med_opts[x])
        trans_type = st.selectbox("Transaction Type", ["Stock In", "Stock Out"])
        qty = st.number_input("Quantity", min_value=1, step=1)
        notes = st.text_area("Notes")
        if trans_type == "Stock In":
            batch_no = st.text_input("Batch Number")
            expiry = st.date_input("Expiry Date", datetime.now() + timedelta(days=365))
            purchase_price = st.number_input("Purchase Price", min_value=0.0, value=0.0)
            selling_price = st.number_input("Selling Price", min_value=0.0, value=0.0)
            if st.button("Add Stock"):
                with get_db_connection() as conn:
                    conn.execute("""
                        INSERT INTO batches (medicine_id, batch_number, quantity, expiry_date, purchase_price, selling_price)
                        VALUES (?,?,?,?,?,?)
                    """, (med_id, batch_no, qty, expiry, purchase_price, selling_price))
                    conn.execute("UPDATE medicines SET current_stock = current_stock + ? WHERE id = ?", (qty, med_id))
                    conn.commit()
                st.success(f"Added {qty} units to stock (Batch: {batch_no})")
                st.rerun()
        else:
            if st.button("Deduct Stock"):
                try:
                    batches = get_best_batch(med_id, qty)
                    with get_db_connection() as conn:
                        for b in batches:
                            conn.execute("UPDATE batches SET quantity = quantity - ? WHERE id = ?", (b['quantity'], b['batch_id']))
                        conn.execute("UPDATE medicines SET current_stock = current_stock - ? WHERE id = ?", (qty, med_id))
                        conn.commit()
                    st.success(f"Deducted {qty} units using {len(batches)} batch(es)")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
    with tab2:
        with get_db_connection() as conn:
            batches = conn.execute("""
                SELECT b.*, m.name as medicine_name
                FROM batches b
                JOIN medicines m ON b.medicine_id = m.id
                ORDER BY b.expiry_date
            """).fetchall()
        if batches:
            df = pd.DataFrame([dict(r) for r in batches])
            st.dataframe(df[['medicine_name','batch_number','quantity','expiry_date','purchase_price','selling_price']])

    with tab3:
        st.subheader("Record Breakage")
        with get_db_connection() as conn:
            meds = conn.execute("SELECT id, name FROM medicines").fetchall()
        med_opts = {m[0]: m[1] for m in meds}
        med_id = st.selectbox("Medicine", list(med_opts.keys()), format_func=lambda x: med_opts[x])
        with get_db_connection() as conn:
            batches = conn.execute("SELECT id, batch_number, quantity FROM batches WHERE medicine_id=? AND quantity>0", (med_id,)).fetchall()
        batch_opts = {b[0]: f"{b[1]} (Stock: {b[2]})" for b in batches}
        if not batch_opts:
            st.warning("No batches available for this medicine.")
            return
        batch_id = st.selectbox("Batch", list(batch_opts.keys()), format_func=lambda x: batch_opts[x])
        qty_break = st.number_input("Quantity to break", min_value=1, step=1)
        reason = st.text_input("Reason")
        if st.button("Record Breakage"):
            with get_db_connection() as conn:
                batch = conn.execute("SELECT quantity FROM batches WHERE id=?", (batch_id,)).fetchone()
                if batch[0] >= qty_break:
                    conn.execute("UPDATE batches SET quantity = quantity - ? WHERE id=?", (qty_break, batch_id))
                    conn.execute("UPDATE medicines SET current_stock = current_stock - ? WHERE id=?", (qty_break, med_id))
                    conn.execute("INSERT INTO inventory_transactions (medicine_id, batch_id, transaction_type, quantity, notes) VALUES (?,?,'BREAKAGE',?,?)", (med_id, batch_id, -qty_break, reason))
                    conn.commit()
                    st.success("Breakage recorded")
                    st.rerun()
                else:
                    st.error("Insufficient batch quantity")

    with tab4:
        st.subheader("Expired Drugs")
        with get_db_connection() as conn:
            expired = conn.execute("""
                SELECT b.id, m.name, b.batch_number, b.expiry_date, b.quantity
                FROM batches b JOIN medicines m ON b.medicine_id = m.id
                WHERE b.expiry_date < date('now')
            """).fetchall()
        if expired:
            df = pd.DataFrame([dict(r) for r in expired])
            st.dataframe(df)
            if st.button("Remove Expired Batches"):
                with get_db_connection() as conn:
                    conn.execute("DELETE FROM batches WHERE expiry_date < date('now')")
                    conn.commit()
                st.success("Expired batches removed")
                st.rerun()
        else:
            st.info("No expired drugs found")

    with tab5:
        st.subheader("Out of Stock Medicines")
        with get_db_connection() as conn:
            oos = conn.execute("SELECT id, name, current_stock FROM medicines WHERE current_stock <= 0").fetchall()
        if oos:
            df = pd.DataFrame([dict(r) for r in oos])
            st.dataframe(df)
        else:
            st.info("All medicines are in stock")

    with tab6:
        st.subheader("Price Change")
        with get_db_connection() as conn:
            meds = conn.execute("SELECT id, name, unit_price FROM medicines").fetchall()
        med_opts = {m[0]: f"{m[1]} (Current: ${m[2]:.2f})" for m in meds}
        med_id = st.selectbox("Select Medicine", list(med_opts.keys()), format_func=lambda x: med_opts[x])
        new_price = st.number_input("New Price ($)", min_value=0.0, step=0.01)
        if st.button("Update Price"):
            with get_db_connection() as conn:
                conn.execute("UPDATE medicines SET unit_price = ? WHERE id = ?", (new_price, med_id))
                conn.commit()
            st.success("Price updated successfully")
            st.rerun()

def render_stocktake():
    require_permission("inventory")
    st.title("📋 Stocktake Management")
    tab1, tab2, tab3, tab4 = st.tabs(["Prepare", "Capture Counts", "Close Stocktake", "Cycle Count"])
    with tab1:
        st.subheader("Prepare New Stocktake")
        name = st.text_input("Stocktake Name")
        if st.button("Prepare Stocktake"):
            if name:
                with get_db_connection() as conn:
                    conn.execute("INSERT INTO stocktakes (name, prepared_by, status) VALUES (?, ?, 'prepared')", (name, st.session_state.user['id']))
                    stocktake_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    medicines = conn.execute("SELECT id, current_stock FROM medicines").fetchall()
                    for med in medicines:
                        conn.execute("INSERT INTO stocktake_items (stocktake_id, medicine_id, expected_quantity, counted_quantity) VALUES (?,?,?,0)", (stocktake_id, med[0], med[1]))
                    conn.commit()
                st.success(f"Stocktake '{name}' prepared")
                st.rerun()
            else:
                st.error("Please enter a name")
        with get_db_connection() as conn:
            stocktakes = conn.execute("SELECT id, name, status, prepared_at FROM stocktakes WHERE status='prepared' ORDER BY prepared_at DESC").fetchall()
        if stocktakes:
            st.subheader("Open Stocktakes")
            for stk in stocktakes:
                st.write(f"{stk[1]} - Prepared: {stk[3]} - Status: {stk[2]}")
                if st.button(f"Capture Counts", key=f"capture_{stk[0]}"):
                    st.session_state.stocktake_id = stk[0]
                    st.rerun()
    with tab2:
        if 'stocktake_id' not in st.session_state:
            st.info("Please prepare or select a stocktake first")
        else:
            stocktake_id = st.session_state.stocktake_id
            with get_db_connection() as conn:
                items = conn.execute("""
                    SELECT si.id, m.name, si.expected_quantity, si.counted_quantity
                    FROM stocktake_items si JOIN medicines m ON si.medicine_id = m.id
                    WHERE si.stocktake_id = ?
                """, (stocktake_id,)).fetchall()
            st.write(f"Stocktake ID: {stocktake_id}")
            for item in items:
                col1, col2, col3 = st.columns([3,1,1])
                col1.write(item[1])
                col2.write(f"Expected: {item[2]}")
                new_count = col3.number_input("Counted", value=item[3], key=f"count_{item[0]}")
                with get_db_connection() as conn2:
                    conn2.execute("UPDATE stocktake_items SET counted_quantity = ? WHERE id = ?", (new_count, item[0]))
                    conn2.commit()
            if st.button("Save All Counts"):
                with get_db_connection() as conn:
                    conn.execute("UPDATE stocktake_items SET variance = counted_quantity - expected_quantity WHERE stocktake_id = ?", (stocktake_id,))
                    conn.commit()
                st.success("Counts saved. You can now close the stocktake.")
    with tab3:
        st.subheader("Close Stocktake")
        with get_db_connection() as conn:
            stocktakes = conn.execute("SELECT id, name FROM stocktakes WHERE status='prepared'").fetchall()
        if stocktakes:
            stk_opts = {s[0]: s[1] for s in stocktakes}
            stk_id = st.selectbox("Select Stocktake to Close", list(stk_opts.keys()), format_func=lambda x: stk_opts[x])
            if st.button("Close and Apply Variances"):
                with get_db_connection() as conn:
                    items = conn.execute("SELECT medicine_id, variance FROM stocktake_items WHERE stocktake_id=?", (stk_id,)).fetchall()
                    for it in items:
                        if it[1] != 0:
                            conn.execute("UPDATE medicines SET current_stock = current_stock + ? WHERE id = ?", (it[1], it[0]))
                            conn.execute("INSERT INTO inventory_transactions (medicine_id, transaction_type, quantity, notes, created_by) VALUES (?, 'ADJUST', ?, ?, ?)", (it[0], it[1], f"Stocktake adjustment", st.session_state.user['id']))
                    conn.execute("UPDATE stocktakes SET status='closed', closed_by=?, closed_at=CURRENT_TIMESTAMP WHERE id=?", (st.session_state.user['id'], stk_id))
                    conn.commit()
                st.success("Stocktake closed and variances applied")
                st.rerun()
        else:
            st.info("No open stocktakes")
    with tab4:
        st.subheader("Cycle Count")
        with get_db_connection() as conn:
            medicines = conn.execute("SELECT id, name FROM medicines").fetchall()
        med_opts = {m[0]: m[1] for m in medicines}
        med_id = st.selectbox("Select Medicine", list(med_opts.keys()), format_func=lambda x: med_opts[x])
        counted_qty = st.number_input("Counted Quantity", min_value=0, step=1)
        if st.button("Update Cycle Count"):
            with get_db_connection() as conn:
                old_stock = conn.execute("SELECT current_stock FROM medicines WHERE id=?", (med_id,)).fetchone()[0]
                variance = counted_qty - old_stock
                conn.execute("UPDATE medicines SET current_stock = ? WHERE id=?", (counted_qty, med_id))
                conn.execute("INSERT INTO inventory_transactions (medicine_id, transaction_type, quantity, notes, created_by) VALUES (?, 'CYCLE_COUNT', ?, ?, ?)", (med_id, variance, f"Cycle count: expected {old_stock}, counted {counted_qty}", st.session_state.user['id']))
                conn.commit()
            st.success(f"Stock updated to {counted_qty}")
            st.rerun()

def render_patients():
    require_permission("patients_view")
    st.title("👥 Patient Management")
    tab1, tab2 = st.tabs(["Patient List", "Register Patient"])
    with tab1:
        search = st.text_input("Search")
        with get_db_connection() as conn:
            if search:
                rows = conn.execute("""
                    SELECT p.*, m.name as medical_aid_name
                    FROM patients p
                    LEFT JOIN medical_aids m ON p.medical_aid_id = m.id
                    WHERE p.first_name LIKE ? OR p.last_name LIKE ? OR p.patient_id LIKE ? OR p.phone LIKE ?
                """, (f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%")).fetchall()
            else:
                rows = conn.execute("""
                    SELECT p.*, m.name as medical_aid_name
                    FROM patients p
                    LEFT JOIN medical_aids m ON p.medical_aid_id = m.id
                    LIMIT 50
                """).fetchall()
        for r in rows:
            with st.expander(f"{r['first_name']} {r['last_name']} (ID: {r['patient_id']})"):
                col1, col2 = st.columns(2)
                col1.write(f"📞 Phone: {r['phone']}")
                col1.write(f"📧 Email: {r['email']}")
                col1.write(f"🏥 Medical Aid: {r['medical_aid_name']} - {r['medical_aid_number']}")
                col2.write(f"🩸 Blood Group: {r['blood_group']}")
                col2.write(f"⚠️ Allergies: {r['allergies'] or 'None'}")
                col2.write(f"📅 DOB: {r['date_of_birth']}")
    with tab2:
        st.subheader("Register New Patient")
        col1, col2 = st.columns(2)
        with col1:
            first = st.text_input("First Name")
            last = st.text_input("Last Name")
            dob = st.date_input("Date of Birth", datetime.now() - timedelta(days=365*30))
            gender = st.selectbox("Gender", ["Male", "Female", "Other"])
            phone = st.text_input("Phone")
            email = st.text_input("Email")
        with col2:
            address = st.text_area("Address")
            with get_db_connection() as conn:
                aids = conn.execute("SELECT id, name FROM medical_aids").fetchall()
            aid_opts = {a[0]: a[1] for a in aids}
            aid_id = st.selectbox("Medical Aid Society", list(aid_opts.keys()), format_func=lambda x: aid_opts[x])
            aid_number = st.text_input("Medical Aid Number")
            blood_group = st.selectbox("Blood Group", ["A+","A-","B+","B-","O+","O-","AB+","AB-"])
            allergies = st.text_area("Allergies")
        if st.button("Register Patient"):
            if first and last:
                pid = f"PAT{datetime.now().strftime('%Y%m%d%H%M%S')}"
                with get_db_connection() as conn:
                    conn.execute("""
                        INSERT INTO patients (patient_id, first_name, last_name, date_of_birth, gender, phone, email,
                                              address, medical_aid_id, medical_aid_number, blood_group, allergies)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (pid, first, last, dob, gender, phone, email, address, aid_id, aid_number, blood_group, allergies))
                    conn.commit()
                st.success(f"Patient registered with ID: {pid}")
                st.rerun()
            else:
                st.error("First and last name are required")

def render_medical_aid_societies():
    require_permission("patients_view")
    st.title("🏥 Medical Aid Societies")
    tab1, tab2 = st.tabs(["List", "Add/Edit"])
    with tab1:
        with get_db_connection() as conn:
            aids = conn.execute("SELECT * FROM medical_aids").fetchall()
        for a in aids:
            with st.expander(f"{a['name']} ({a['code']})"):
                st.write(f"Contact: {a['contact_person']}, Phone: {a['phone']}, Email: {a['email']}")
                st.write(f"Address: {a['address']}")
    with tab2:
        st.subheader("Add New Medical Aid")
        name = st.text_input("Name")
        code = st.text_input("Code")
        contact = st.text_input("Contact Person")
        phone = st.text_input("Phone")
        email = st.text_input("Email")
        address = st.text_area("Address")
        if st.button("Add Medical Aid"):
            if name:
                with get_db_connection() as conn:
                    conn.execute("""
                        INSERT INTO medical_aids (name, code, contact_person, phone, email, address)
                        VALUES (?,?,?,?,?,?)
                    """, (name, code, contact, phone, email, address))
                    conn.commit()
                st.success("Medical aid added")
                st.rerun()
            else:
                st.error("Name required")

def render_prescriptions():
    require_permission("prescriptions")
    st.title("📋 Prescription Management")
    tab1, tab2 = st.tabs(["Pending Prescriptions", "New Prescription", "Script Maintenance"])
    with tab1:
        with get_db_connection() as conn:
            pending = conn.execute("""
                SELECT p.*, pat.first_name, pat.last_name
                FROM prescriptions p
                JOIN patients pat ON p.patient_id = pat.id
                WHERE p.status = 'pending'
            """).fetchall()
        if not pending:
            st.info("No pending prescriptions")
        for p in pending:
            with st.expander(f"#{p['prescription_number']} - {p['first_name']} {p['last_name']}"):
                st.write(f"Doctor: {p['doctor_name']}")
                st.write(f"Prescribed Date: {p['prescribed_date']}")
                items = conn.execute("""
                    SELECT pi.*, m.name, m.current_stock
                    FROM prescription_items pi
                    JOIN medicines m ON pi.medicine_id = m.id
                    WHERE pi.prescription_id = ?
                """, (p['id'],)).fetchall()
                stock_ok = True
                for it in items:
                    st.write(f"- {it['name']}: Qty {it['quantity']}, Stock {it['current_stock']}")
                    if it['quantity'] > it['current_stock']:
                        stock_ok = False
                        st.error(f"⚠️ Insufficient stock for {it['name']}")
                notes = st.text_area("Pharmacist Notes", key=f"notes_{p['id']}")
                col1, col2 = st.columns(2)
                if col1.button("Approve", key=f"app_{p['id']}"):
                    if not stock_ok:
                        st.error("Cannot approve: insufficient stock for some medicines.")
                    else:
                        with get_db_connection() as conn2:
                            conn2.execute("""
                                UPDATE prescriptions
                                SET status = 'approved', pharmacist_notes = ?, approved_by = ?
                                WHERE id = ?
                            """, (notes, st.session_state.user['id'], p['id']))
                            conn2.commit()
                        st.success("Prescription approved")
                        st.rerun()
                if col2.button("Reject", key=f"rej_{p['id']}"):
                    with get_db_connection() as conn2:
                        conn2.execute("UPDATE prescriptions SET status = 'rejected' WHERE id = ?", (p['id'],))
                        conn2.commit()
                    st.success("Prescription rejected")
                    st.rerun()
    with tab2:
        st.subheader("Create Electronic Prescription")
        with get_db_connection() as conn:
            patients = conn.execute("SELECT id, patient_id, first_name, last_name FROM patients").fetchall()
        if not patients:
            st.warning("No patients registered. Please add patients first.")
            return
        pat_opts = {p[0]: f"{p[2]} {p[3]} ({p[1]})" for p in patients}
        patient_id = st.selectbox("Patient", list(pat_opts.keys()), format_func=lambda x: pat_opts[x])
        doctor_name = st.text_input("Doctor Name")
        prescribed_date = st.date_input("Prescribed Date", datetime.now().date())
        expiry_date = st.date_input("Expiry Date", datetime.now().date() + timedelta(days=30))
        with get_db_connection() as conn:
            all_meds = conn.execute("SELECT id, name FROM medicines").fetchall()
        if not all_meds:
            st.warning("No medicines available. Add medicines first.")
            return
        med_opts = {m[0]: m[1] for m in all_meds}
        if 'pres_items' not in st.session_state:
            st.session_state.pres_items = []
        col1, col2, col3, col4 = st.columns([2,1,2,1])
        with col1:
            med_sel = st.selectbox("Medicine", list(med_opts.keys()), format_func=lambda x: med_opts[x], key="med_sel")
        with col2:
            qty = st.number_input("Quantity", min_value=1, value=1, key="qty_sel")
        with col3:
            dosage = st.text_input("Dosage", placeholder="e.g., 1 tablet twice daily", key="dosage_sel")
        with col4:
            duration = st.text_input("Duration", placeholder="7 days", key="dur_sel")
        if st.button("Add Medicine"):
            st.session_state.pres_items.append({
                "medicine_id": med_sel,
                "name": med_opts[med_sel],
                "quantity": qty,
                "dosage": dosage,
                "duration": duration
            })
            st.success(f"Added {med_opts[med_sel]} to prescription")
            st.rerun()
        for idx, it in enumerate(st.session_state.pres_items):
            st.write(f"{idx+1}. {it['name']} - Qty {it['quantity']}, Dosage {it['dosage']}")
            if st.button(f"Remove {idx}", key=f"rem_{idx}"):
                st.session_state.pres_items.pop(idx)
                st.success("Item removed")
                st.rerun()
        if st.button("Save Prescription") and patient_id:
            if not st.session_state.pres_items:
                st.error("Add at least one medicine")
            else:
                pres_num = f"RX{datetime.now().strftime('%Y%m%d%H%M%S')}"
                with get_db_connection() as conn:
                    conn.execute("""
                        INSERT INTO prescriptions (prescription_number, patient_id, doctor_name, prescribed_date, expiry_date, status)
                        VALUES (?,?,?,?,?,'pending')
                    """, (pres_num, patient_id, doctor_name, prescribed_date, expiry_date))
                    pres_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    for it in st.session_state.pres_items:
                        conn.execute("""
                            INSERT INTO prescription_items (prescription_id, medicine_id, dosage, duration, instructions, quantity)
                            VALUES (?,?,?,?,?,?)
                        """, (pres_id, it['medicine_id'], it['dosage'], it['duration'], it['dosage'], it['quantity']))
                    conn.commit()
                st.session_state.pres_items = []
                st.success(f"Prescription {pres_num} created")
                st.rerun()
    with tab3:
        st.subheader("Script Maintenance")
        with get_db_connection() as conn:
            scripts = conn.execute("""
                SELECT p.id, p.prescription_number, pat.first_name, pat.last_name, p.date, p.status
                FROM prescriptions p
                JOIN patients pat ON p.patient_id = pat.id
                ORDER BY p.date DESC
            """).fetchall()
        if scripts:
            df = pd.DataFrame([dict(r) for r in scripts])
            st.dataframe(df)
            for r in scripts:
                if st.button(f"Reprint Script #{r['prescription_number']}", key=f"reprint_{r['id']}"):
                    with get_db_connection() as conn2:
                        items = conn2.execute("""
                            SELECT pi.*, m.name
                            FROM prescription_items pi JOIN medicines m ON pi.medicine_id=m.id
                            WHERE pi.prescription_id = ?
                        """, (r['id'],)).fetchall()
                    # Generate PDF
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_font("Arial", "B", 16)
                    pdf.cell(200, 10, "Prescription", ln=1, align='C')
                    pdf.set_font("Arial", "", 12)
                    pdf.cell(200, 10, f"Number: {r['prescription_number']}", ln=1)
                    pdf.cell(200, 10, f"Patient: {r['first_name']} {r['last_name']}", ln=1)
                    pdf.cell(200, 10, f"Date: {r['date']}", ln=1)
                    pdf.ln(10)
                    pdf.set_font("Arial", "B", 10)
                    pdf.cell(80, 10, "Medicine", 1)
                    pdf.cell(30, 10, "Qty", 1)
                    pdf.cell(50, 10, "Dosage", 1)
                    pdf.cell(40, 10, "Instructions", 1)
                    pdf.ln()
                    pdf.set_font("Arial", "", 10)
                    for it in items:
                        pdf.cell(80, 10, it['name'][:30], 1)
                        pdf.cell(30, 10, str(it['quantity']), 1)
                        pdf.cell(50, 10, it['dosage'][:20], 1)
                        pdf.cell(40, 10, it['instructions'][:20], 1)
                        pdf.ln()
                    pdf_bytes = pdf.output(dest='S').encode('latin1')
                    st.download_button(f"Download PDF", data=pdf_bytes, file_name=f"prescription_{r['prescription_number']}.pdf", mime="application/pdf")

def render_sales_billing():
    require_permission("sales")
    st.title("💰 Sales & Billing")
    if 'cart' not in st.session_state:
        st.session_state.cart = []
    col1, col2 = st.columns([2,1])
    with col1:
        with get_db_connection() as conn:
            meds = conn.execute("SELECT id, name, unit_price, current_stock FROM medicines WHERE current_stock > 0").fetchall()
        if not meds:
            st.warning("No medicines in stock")
        else:
            med_opts = {m[0]: f"{m[1]} - ${m[2]:.2f}" for m in meds}
            med_id = st.selectbox("Medicine", list(med_opts.keys()), format_func=lambda x: med_opts[x])
            med = next(m for m in meds if m[0] == med_id)
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
                    st.success(f"Added {qty} x {med[1]} to cart")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
    with col2:
        if st.session_state.cart:
            df = pd.DataFrame([{"Item": c['name'], "Qty": c['quantity'], "Price": c['unit_price'], "Total": c['total']} for c in st.session_state.cart])
            st.dataframe(df)
            subtotal = sum(c['total'] for c in st.session_state.cart)
            discount = st.number_input("Discount ($)", min_value=0.0, value=0.0)
            settings = get_settings_dict()
            gst_rate = float(settings.get("gst_rate", 5))
            tax = (subtotal - discount) * gst_rate / 100
            net = subtotal - discount + tax
            st.write(f"**Subtotal: ${subtotal:.2f}**")
            st.write(f"**Tax (GST {gst_rate}%): ${tax:.2f}**")
            st.write(f"**Net Amount: ${net:.2f}**")
            patient_search = st.text_input("Patient ID (optional)")
            payment_method = st.selectbox("Payment Method", ["Cash", "Card", "Medical Aid", "UPI"])
            medical_aid_claim = payment_method == "Medical Aid"
            if st.button("Complete Sale"):
                with get_db_connection() as conn:
                    patient_id = None
                    if patient_search:
                        pat = conn.execute("SELECT id FROM patients WHERE patient_id = ?", (patient_search,)).fetchone()
                        if pat:
                            patient_id = pat[0]
                    invoice_no = f"INV{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    loyalty_points = int(net * 0.05)
                    conn.execute("""
                        INSERT INTO sales (invoice_number, patient_id, user_id, total_amount, discount, tax, net_amount,
                                          payment_method, loyalty_points_earned)
                        VALUES (?,?,?,?,?,?,?,?,?)
                    """, (invoice_no, patient_id, st.session_state.user['id'], subtotal, discount, tax, net, payment_method, loyalty_points))
                    sale_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    for item in st.session_state.cart:
                        for b in item['batches']:
                            conn.execute("""
                                INSERT INTO sale_items (sale_id, medicine_id, batch_id, quantity, unit_price, total)
                                VALUES (?,?,?,?,?,?)
                            """, (sale_id, item['medicine_id'], b['batch_id'], b['quantity'], item['unit_price'], b['quantity'] * item['unit_price']))
                            conn.execute("UPDATE batches SET quantity = quantity - ? WHERE id = ?", (b['quantity'], b['batch_id']))
                        conn.execute("UPDATE medicines SET current_stock = current_stock - ? WHERE id = ?", (item['quantity'], item['medicine_id']))
                    if patient_id:
                        cur = conn.cursor()
                        cur.execute("SELECT points FROM loyalty_points WHERE patient_id = ?", (patient_id,))
                        exists = cur.fetchone()
                        if exists:
                            cur.execute("UPDATE loyalty_points SET points = points + ? WHERE patient_id = ?", (loyalty_points, patient_id))
                        else:
                            cur.execute("INSERT INTO loyalty_points (patient_id, points, redeemed) VALUES (?, ?, 0)", (patient_id, loyalty_points))
                    conn.commit()
                receipt_data = {
                    "invoice_number": invoice_no,
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "patient_name": patient_search or "Walk-in Customer",
                    "items": [{"name": c['name'], "quantity": c['quantity'], "price": c['unit_price'], "total": c['total']} for c in st.session_state.cart],
                    "total": subtotal,
                    "discount": discount,
                    "tax": tax,
                    "net_amount": net
                }
                pdf_bytes = generate_invoice_pdf(receipt_data)
                st.success(f"Sale complete! Invoice: {invoice_no}")
                st.download_button("Download Receipt (PDF)", data=pdf_bytes, file_name=f"{invoice_no}.pdf", mime="application/pdf")
                st.session_state.cart = []
                st.rerun()
        else:
            st.info("Cart is empty")

def render_sales_returns():
    require_permission("sales")
    st.title("🔄 Sales Returns")
    invoice = st.text_input("Enter Invoice Number")
    if invoice:
        with get_db_connection() as conn:
            sale = conn.execute("SELECT id, net_amount FROM sales WHERE invoice_number = ?", (invoice,)).fetchone()
            if not sale:
                st.error("Invoice not found")
                return
            items = conn.execute("""
                SELECT si.id, m.name, si.quantity, si.unit_price
                FROM sale_items si
                JOIN medicines m ON si.medicine_id = m.id
                WHERE si.sale_id = ?
            """, (sale[0],)).fetchall()
        if not items:
            st.info("No items found for this invoice")
            return
        for it in items:
            col1, col2, col3 = st.columns([3,1,1])
            col1.write(f"{it[1]} - Sold: {it[2]}")
            ret_qty = col2.number_input("Return Qty", min_value=0, max_value=it[2], key=f"ret_{it[0]}")
            if col3.button("Return", key=f"retbtn_{it[0]}"):
                if ret_qty > 0:
                    refund = ret_qty * it[3]
                    with get_db_connection() as conn2:
                        conn2.execute("UPDATE medicines SET current_stock = current_stock + ? WHERE id = (SELECT medicine_id FROM sale_items WHERE id = ?)", (ret_qty, it[0]))
                        conn2.execute("""
                            INSERT INTO sales_returns (original_sale_id, sale_item_id, quantity_returned, refund_amount, reason, created_by)
                            VALUES (?,?,?,?,?,?)
                        """, (sale[0], it[0], ret_qty, refund, "Customer return", st.session_state.user['id']))
                        conn2.commit()
                    st.success(f"Returned {ret_qty} units, refund ${refund:.2f}")
                    st.rerun()
                else:
                    st.warning("Enter quantity > 0")

def render_label_printing():
    require_permission("label_print")
    st.title("🏷️ Label Printing")
    with get_db_connection() as conn:
        meds = conn.execute("SELECT id, name, generic_name, unit_price FROM medicines").fetchall()
    if not meds:
        st.warning("No medicines found")
        return
    med_opts = {m[0]: f"{m[1]} ({m[2]})" for m in meds}
    med_id = st.selectbox("Select Medicine", list(med_opts.keys()), format_func=lambda x: med_opts[x])
    med = next(m for m in meds if m[0] == med_id)
    settings = get_settings_dict()
    st.subheader("Label Preview")
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**{settings.get('pharmacy_name', 'Pharmacy')}**")
        st.write(f"**Medicine:** {med[1]}")
        st.write(f"**Generic:** {med[2]}")
        st.write(f"**Price:** ${med[3]:.2f}")
        dosage = st.text_input("Dosage Instructions", "Take as directed by physician")
        st.write(f"**Pharmacist:** {st.session_state.user['full_name']}")
    with col2:
        qr = generate_qr(f"Medicine: {med[1]}\nDosage: {dosage}")
        st.image(qr, width=150)
        bc = generate_barcode(str(med[0]))
        st.image(bc, width=200)
    if st.button("Generate & Download Label"):
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", "B", 16)
        pdf.cell(200, 10, settings.get("pharmacy_name", "Pharmacy"), ln=1, align='C')
        pdf.set_font("Arial", "", 12)
        pdf.cell(200, 10, f"Medicine: {med[1]}", ln=1)
        pdf.cell(200, 10, f"Generic: {med[2]}", ln=1)
        pdf.cell(200, 10, f"Price: ${med[3]:.2f}", ln=1)
        pdf.cell(200, 10, f"Dosage: {dosage}", ln=1)
        pdf.cell(200, 10, f"Pharmacist: {st.session_state.user['full_name']}", ln=1)
        pdf.cell(200, 10, f"Date: {datetime.now().strftime('%Y-%m-%d')}", ln=1)
        qr_path = tempfile.mktemp(".png")
        qr.save(qr_path)
        pdf.image(qr_path, x=150, y=80, w=40)
        os.unlink(qr_path)
        pdf_bytes = pdf.output(dest='S').encode('latin1')
        st.download_button("Download Label (PDF)", data=pdf_bytes, file_name=f"label_{med[1]}.pdf", mime="application/pdf")
        st.success("Label generated")

def render_suppliers():
    require_permission("suppliers")
    st.title("🚚 Supplier Management")
    tab1, tab2 = st.tabs(["Suppliers", "Purchase Orders"])
    with tab1:
        with get_db_connection() as conn:
            sups = conn.execute("SELECT * FROM suppliers").fetchall()
        for s in sups:
            with st.expander(f"{s['name']} - {s.get('contact_person', '')}"):
                col1, col2 = st.columns(2)
                col1.write(f"📞 {s['phone']}")
                col1.write(f"📧 {s['email']}")
                col2.write(f"GST: {s['gst_number']}")
                col2.write(f"Terms: {s['payment_terms']}")
        st.subheader("Add New Supplier")
        with st.form("add_supplier"):
            name = st.text_input("Supplier Name")
            contact = st.text_input("Contact Person")
            phone = st.text_input("Phone")
            email = st.text_input("Email")
            address = st.text_area("Address")
            gst = st.text_input("GST Number")
            terms = st.text_input("Payment Terms")
            if st.form_submit_button("Add Supplier"):
                if name:
                    with get_db_connection() as conn:
                        conn.execute("""
                            INSERT INTO suppliers (name, contact_person, phone, email, address, gst_number, payment_terms)
                            VALUES (?,?,?,?,?,?,?)
                        """, (name, contact, phone, email, address, gst, terms))
                        conn.commit()
                    st.success(f"Supplier '{name}' added")
                    st.rerun()
                else:
                    st.error("Supplier name is required")
    with tab2:
        st.subheader("Purchase Orders")
        with get_db_connection() as conn:
            pos = conn.execute("SELECT * FROM purchase_orders ORDER BY created_at DESC LIMIT 50").fetchall()
        if pos:
            df = pd.DataFrame([dict(r) for r in pos])
            st.dataframe(df)

def render_reports():
    require_permission("reports")
    st.title("📊 Reports")
    report_type = st.selectbox("Select Report", ["Daily Sales", "Monthly Sales", "Inventory Report", "Expiry Report", "Profit Report", "Medical Aid Report", "Trading Report"])
    if report_type == "Daily Sales":
        date_sel = st.date_input("Select Date", datetime.now().date())
        with get_db_connection() as conn:
            rows = conn.execute("""
                SELECT s.invoice_number, s.net_amount, s.payment_method, s.created_at, u.full_name
                FROM sales s
                JOIN users u ON s.user_id = u.id
                WHERE DATE(s.created_at) = ?
            """, (date_sel.isoformat(),)).fetchall()
        df = pd.DataFrame([dict(r) for r in rows])
        st.dataframe(df)
        if not df.empty:
            st.metric("Total Sales", f"${df['net_amount'].sum():.2f}")
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            st.download_button("Export to Excel", data=buf.getvalue(), file_name=f"sales_{date_sel}.xlsx")
    elif report_type == "Monthly Sales":
        month = st.selectbox("Month", range(1,13), format_func=lambda x: datetime(2000,x,1).strftime("%B"))
        year = st.number_input("Year", min_value=2020, value=datetime.now().year)
        with get_db_connection() as conn:
            rows = conn.execute("""
                SELECT strftime('%Y-%m-%d', created_at) as day, SUM(net_amount) as sales
                FROM sales
                WHERE strftime('%Y', created_at) = ? AND strftime('%m', created_at) = ?
                GROUP BY day
                ORDER BY day
            """, (str(year), f"{month:02d}")).fetchall()
        if rows:
            df = pd.DataFrame([{"date": r[0], "sales": r[1]} for r in rows])
            fig = px.line(df, x='date', y='sales', title=f"{datetime(year,month,1).strftime('%B %Y')} Sales")
            st.plotly_chart(fig)
    elif report_type == "Inventory Report":
        with get_db_connection() as conn:
            rows = conn.execute("SELECT name, current_stock, reorder_level, unit_price FROM medicines").fetchall()
        if rows:
            df = pd.DataFrame([dict(r) for r in rows])
            st.dataframe(df)
            fig = px.bar(df, x='name', y='current_stock', title='Current Stock Levels')
            st.plotly_chart(fig)
        else:
            st.info("No medicine data")
    elif report_type == "Expiry Report":
        expiring = get_expiring(90)
        st.dataframe(expiring)
        if not expiring.empty:
            fig = px.bar(expiring, x='name', y='qty', color='expiry', title='Expiring Batches (Next 90 Days)')
            st.plotly_chart(fig)
    elif report_type == "Profit Report":
        with get_db_connection() as conn:
            rows = conn.execute("""
                SELECT strftime('%Y-%m', created_at) as month, SUM(net_amount) as total_sales
                FROM sales
                GROUP BY month
                ORDER BY month DESC
                LIMIT 6
            """).fetchall()
        if rows:
            df = pd.DataFrame([{"month": r[0], "sales": r[1]} for r in rows])
            fig = px.line(df, x='month', y='sales', title='Monthly Sales Trend (Last 6 Months)')
            st.plotly_chart(fig)
    elif report_type == "Medical Aid Report":
        with get_db_connection() as conn:
            rows = conn.execute("""
                SELECT ma.name as medical_aid, SUM(s.net_amount) as total
                FROM sales s
                LEFT JOIN patients p ON s.patient_id = p.id
                LEFT JOIN medical_aids ma ON p.medical_aid_id = ma.id
                WHERE s.payment_method = 'Medical Aid'
                GROUP BY ma.name
            """).fetchall()
        if rows:
            df = pd.DataFrame([dict(r) for r in rows])
            st.dataframe(df)
            fig = px.pie(df, values='total', names='medical_aid', title='Medical Aid Claims')
            st.plotly_chart(fig)
    elif report_type == "Trading Report":
        with get_db_connection() as conn:
            total_sales = conn.execute("SELECT COALESCE(SUM(net_amount),0) FROM sales").fetchone()[0]
            total_cost = conn.execute("SELECT COALESCE(SUM(purchase_price * quantity),0) FROM sale_items si JOIN batches b ON si.batch_id=b.id").fetchone()[0]
        profit = total_sales - total_cost
        margin = (profit / total_sales * 100) if total_sales > 0 else 0
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Sales", f"${total_sales:,.2f}")
        col2.metric("Cost of Sales", f"${total_cost:,.2f}")
        col3.metric("Gross Profit", f"${profit:,.2f} ({margin:.1f}%)")

def render_staff_management():
    require_permission("staff")
    st.title("👨‍💼 Staff Management")
    tab1, tab2, tab3 = st.tabs(["Employees", "Roles", "Attendance"])
    with tab1:
        with get_db_connection() as conn:
            users = conn.execute("SELECT u.*, r.name as role_name FROM users u JOIN roles r ON u.role_id = r.id").fetchall()
        for u in users:
            st.write(f"{u['full_name']} ({u['username']}) - {u['role_name']}")
        st.subheader("Add New Employee")
        with st.form("add_employee"):
            uname = st.text_input("Username")
            pwd = st.text_input("Password", type="password")
            full = st.text_input("Full Name")
            email = st.text_input("Email")
            with get_db_connection() as conn:
                roles = conn.execute("SELECT id, name FROM roles").fetchall()
            role_opts = {r[0]: r[1] for r in roles}
            role = st.selectbox("Role", list(role_opts.keys()), format_func=lambda x: role_opts[x])
            if st.form_submit_button("Add Employee"):
                if uname and pwd and full:
                    with get_db_connection() as conn:
                        conn.execute("""
                            INSERT INTO users (username, password_hash, full_name, email, role_id, must_change_password)
                            VALUES (?,?,?,?,?,1)
                        """, (uname, generate_password_hash(pwd), full, email, role))
                        conn.commit()
                    st.success(f"Employee {full} added with role {role_opts[role]}")
                    st.rerun()
                else:
                    st.error("Please fill all required fields")
    with tab2:
        st.subheader("Role Permissions")
        with get_db_connection() as conn:
            roles = conn.execute("SELECT * FROM roles").fetchall()
            for r in roles:
                st.write(f"**{r['name']}**")
                perms = json.loads(r['permissions'])
                st.json(perms)
    with tab3:
        st.subheader("Today's Attendance")
        today = date.today()
        with get_db_connection() as conn:
            staff = conn.execute("SELECT id, full_name FROM users WHERE is_active = 1").fetchall()
        for emp in staff:
            col1, col2, col3 = st.columns([2,1,1])
            col1.write(emp[1])
            check_in = col2.time_input("Check In", value=datetime.now().time(), key=f"in_{emp[0]}")
            check_out = col3.time_input("Check Out", value=datetime.now().time(), key=f"out_{emp[0]}")
            if st.button(f"Mark Attendance", key=f"att_{emp[0]}"):
                with get_db_connection() as conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO staff_attendance (user_id, date, check_in, check_out, status)
                        VALUES (?,?,?,?,'present')
                    """, (emp[0], today, check_in.strftime("%H:%M"), check_out.strftime("%H:%M")))
                    conn.commit()
                st.success(f"Attendance marked for {emp[1]}")

def render_notifications():
    require_permission("all")
    st.title("🔔 Notifications")
    with get_db_connection() as conn:
        notifs = conn.execute("SELECT * FROM notifications ORDER BY created_at DESC").fetchall()
    if not notifs:
        st.info("No notifications")
    for n in notifs:
        if n['type'] == 'warning':
            st.warning(f"**{n['title']}**: {n['message']}")
        elif n['type'] == 'danger':
            st.error(f"**{n['title']}**: {n['message']}")
        else:
            st.info(f"**{n['title']}**: {n['message']}")
    if st.button("Clear All Notifications"):
        with get_db_connection() as conn:
            conn.execute("DELETE FROM notifications")
            conn.commit()
        st.success("All notifications cleared")
        st.rerun()

def render_audit_logs():
    require_permission("audit")
    st.title("📜 Audit Logs")
    with get_db_connection() as conn:
        logs = conn.execute("""
            SELECT al.*, u.full_name
            FROM audit_logs al
            LEFT JOIN users u ON al.user_id = u.id
            ORDER BY al.created_at DESC
            LIMIT 100
        """).fetchall()
    if logs:
        df = pd.DataFrame([dict(r) for r in logs])
        st.dataframe(df[['created_at', 'full_name', 'action', 'details']])
    else:
        st.info("No audit logs yet")

def render_advanced_features():
    require_permission("advanced")
    st.title("🚀 Advanced Features")
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "Drug Interactions", "Stock Forecasting", "Loyalty Program", "Appointments",
        "Usage Analytics", "Auto POs"
    ])
    with tab1:
        with get_db_connection() as conn:
            meds = conn.execute("SELECT id, name FROM medicines").fetchall()
        opts = {m[0]: m[1] for m in meds}
        if opts:
            med1 = st.selectbox("Medicine 1", list(opts.keys()), format_func=lambda x: opts[x], key="inter1")
            med2 = st.selectbox("Medicine 2", list(opts.keys()), format_func=lambda x: opts[x], key="inter2")
            if st.button("Check Interaction"):
                with get_db_connection() as conn:
                    inter = conn.execute("""
                        SELECT severity, description FROM drug_interactions
                        WHERE (medicine1_id = ? AND medicine2_id = ?) OR (medicine1_id = ? AND medicine2_id = ?)
                    """, (med1, med2, med2, med1)).fetchone()
                if inter:
                    st.warning(f"⚠️ Interaction Found: {inter[0]} severity - {inter[1]}")
                else:
                    st.success("No known interactions between these medicines.")
            st.subheader("Add New Interaction")
            sev = st.selectbox("Severity", ["Mild", "Moderate", "Severe"])
            desc = st.text_area("Description")
            if st.button("Add Interaction"):
                if med1 != med2:
                    with get_db_connection() as conn:
                        conn.execute("""
                            INSERT INTO drug_interactions (medicine1_id, medicine2_id, severity, description)
                            VALUES (?,?,?,?)
                        """, (med1, med2, sev, desc))
                        conn.commit()
                    st.success("Interaction added")
                else:
                    st.error("Select two different medicines")
        else:
            st.info("Add medicines first to define interactions.")
    with tab2:
        with get_db_connection() as conn:
            meds = conn.execute("SELECT id, name FROM medicines").fetchall()
        if meds:
            med_for = st.selectbox("Select Medicine", [m[1] for m in meds])
            if med_for:
                med_id = next(m[0] for m in meds if m[1] == med_for)
                forecast = stock_forecast(med_id, 30)
                if forecast:
                    st.info(f"📈 Forecast for next 30 days: **{forecast} units**")
                else:
                    st.warning("Insufficient sales data for forecasting. Add more sales first.")
        else:
            st.info("No medicines available")
    with tab3:
        with get_db_connection() as conn:
            loyalty = conn.execute("""
                SELECT p.first_name, p.last_name, lp.points
                FROM loyalty_points lp
                JOIN patients p ON lp.patient_id = p.id
                ORDER BY lp.points DESC
            """).fetchall()
        if loyalty:
            df = pd.DataFrame([{"name": f"{r[0]} {r[1]}", "points": r[2]} for r in loyalty])
            st.dataframe(df)
            st.metric("Total Points Issued", df['points'].sum())
            points_to_redeem = st.number_input("Redeem Points (100 points = $1)", min_value=0, max_value=int(df['points'].max() if not df.empty else 0))
            if st.button("Redeem"):
                st.info(f"Redeeming {points_to_redeem} points would give ${points_to_redeem/100:.2f} discount.")
        else:
            st.info("No loyalty data yet. Points are earned from sales.")
    with tab4:
        with get_db_connection() as conn:
            patients = conn.execute("SELECT id, patient_id, first_name, last_name FROM patients").fetchall()
        pat_opts = {p[0]: f"{p[2]} {p[3]} ({p[1]})" for p in patients}
        if pat_opts:
            patient_id = st.selectbox("Patient", list(pat_opts.keys()), format_func=lambda x: pat_opts[x])
            app_date = st.date_input("Appointment Date", min_value=datetime.now().date())
            app_time = st.time_input("Appointment Time")
            purpose = st.text_input("Purpose")
            if st.button("Book Appointment"):
                with get_db_connection() as conn:
                    conn.execute("""
                        INSERT INTO appointments (patient_id, appointment_date, appointment_time, purpose)
                        VALUES (?,?,?,?)
                    """, (patient_id, app_date, app_time.strftime("%H:%M"), purpose))
                    conn.commit()
                st.success("Appointment booked successfully")
                st.rerun()
        else:
            st.info("No patients registered. Add patients first.")
    with tab5:
        st.subheader("Usage Analytics")
        col1, col2 = st.columns(2)
        with col1:
            days = st.number_input("Days (last N days)", min_value=7, max_value=365, value=30)
        with col2:
            with get_db_connection() as conn:
                all_meds = conn.execute("SELECT id, name FROM medicines").fetchall()
            med_choice = st.selectbox("Select Medicine (optional)", ["All Medicines"] + [m[1] for m in all_meds])
        df_usage = usage_analytics(None if med_choice == "All Medicines" else next(m[0] for m in all_meds if m[1] == med_choice), days)
        if not df_usage.empty:
            fig = px.line(df_usage, x='date', y='quantity', title=f"Daily Consumption - {med_choice}")
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df_usage)
        else:
            st.info("No sales data for the selected period.")
    with tab6:
        st.subheader("Automated Purchase Orders")
        if st.button("Generate POs for Low-Stock Items"):
            count = auto_create_purchase_orders()
            if count:
                st.success(f"Generated {count} purchase order(s) for low-stock medicines.")
            else:
                st.info("No low-stock items requiring purchase orders.")
        with get_db_connection() as conn:
            pos = conn.execute("SELECT * FROM purchase_orders WHERE po_number LIKE 'POAUTO%' ORDER BY created_at DESC LIMIT 20").fetchall()
        if pos:
            st.subheader("Recent Auto‑Generated POs")
            df_po = pd.DataFrame([dict(r) for r in pos])
            st.dataframe(df_po[['po_number', 'order_date', 'expected_delivery', 'status']])
        else:
            st.info("No auto‑generated purchase orders yet.")

def render_ai_assistant():
    require_permission("all")
    st.title("🤖 AI Pharmacy Assistant")
    st.markdown("Ask me about medicines, symptoms, stock status, expiries, or drug interactions.")
    if "ai_msgs" not in st.session_state:
        st.session_state.ai_msgs = [{"role": "assistant", "content": "Hello! I'm your pharmacy AI assistant. How can I help you today?"}]
    for msg in st.session_state.ai_msgs:
        if msg["role"] == "user":
            st.chat_message("user").write(msg["content"])
        else:
            st.chat_message("assistant").write(msg["content"])
    user_input = st.chat_input("Type your question here...")
    if user_input:
        st.session_state.ai_msgs.append({"role": "user", "content": user_input})
        st.chat_message("user").write(user_input)
        response = ai_response(user_input)
        st.session_state.ai_msgs.append({"role": "assistant", "content": response})
        st.chat_message("assistant").write(response)
        log_audit(st.session_state.user['id'], "AI_QUERY", user_input[:100])

def render_settings():
    require_permission("all")
    if st.session_state.user['role_name'] != "Admin":
        st.error("Only Admin can access settings.")
        return
    st.title("⚙️ System Settings")
    settings = get_settings_dict()
    st.subheader("General Settings")
    ph_name = st.text_input("Pharmacy Name", settings.get("pharmacy_name", ""))
    ph_addr = st.text_area("Address", settings.get("pharmacy_address", ""))
    ph_phone = st.text_input("Phone", settings.get("pharmacy_phone", ""))
    ph_email = st.text_input("Email", settings.get("pharmacy_email", ""))
    tax_num = st.text_input("Tax Number", settings.get("tax_number", ""))
    license_no = st.text_input("Pharmacist License Number", settings.get("pharmacist_license", ""))
    receipt_footer = st.text_area("Receipt Footer", settings.get("receipt_footer", ""))
    gst_rate = st.number_input("GST Rate (%)", min_value=0.0, max_value=100.0, value=float(settings.get("gst_rate", 5)), step=0.5)
    if st.button("Save Settings"):
        update_setting("pharmacy_name", ph_name)
        update_setting("pharmacy_address", ph_addr)
        update_setting("pharmacy_phone", ph_phone)
        update_setting("pharmacy_email", ph_email)
        update_setting("tax_number", tax_num)
        update_setting("pharmacist_license", license_no)
        update_setting("receipt_footer", receipt_footer)
        update_setting("gst_rate", str(gst_rate))
        st.success("Settings saved successfully")
        st.rerun()
    st.subheader("Backup & Restore")
    if st.button("Create Backup"):
        backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy(DB_PATH, backup_name)
        with open(backup_name, "rb") as f:
            st.download_button("Download Backup", data=f, file_name=backup_name, mime="application/octet-stream")
        st.success("Backup created")
    restore_file = st.file_uploader("Restore from Backup (SQLite .db file)", type=['db'])
    if restore_file and st.button("Restore Backup"):
        temp_path = tempfile.NamedTemporaryFile(delete=False, suffix=".db").name
        with open(temp_path, "wb") as f:
            f.write(restore_file.getbuffer())
        try:
            with sqlite3.connect(temp_path) as test_conn:
                test_conn.execute("SELECT 1 FROM users LIMIT 1")
            shutil.copy(temp_path, DB_PATH)
            os.unlink(temp_path)
            st.success("Database restored. Please restart the app.")
            st.rerun()
        except Exception as e:
            st.error(f"Invalid backup file: {e}")
            os.unlink(temp_path)

def render_printer_setup():
    require_permission("all")
    st.title("🖨️ Printer Setup")
    st.info("Configure default printers for receipts, labels, and prescriptions.")
    receipt_printer = st.text_input("Receipt Printer Name", value="Default Printer")
    label_printer = st.text_input("Label Printer Name", value="Default Label Printer")
    if st.button("Save Printer Settings"):
        update_setting("receipt_printer", receipt_printer)
        update_setting("label_printer", label_printer)
        st.success("Printer settings saved")

def render_calculator():
    require_permission("all")
    st.title("🧮 Calculator")
    st.markdown("""
    <style>
    .calc-btn { width: 100%; margin: 2px; }
    </style>
    """, unsafe_allow_html=True)
    if 'calc_expr' not in st.session_state:
        st.session_state.calc_expr = ""
    display = st.text_input("", value=st.session_state.calc_expr, key="calc_display")
    cols = [
        ["7","8","9","/"],
        ["4","5","6","*"],
        ["1","2","3","-"],
        ["0",".","=","+"],
        ["C"]
    ]
    for row in cols:
        btns = st.columns(len(row))
        for i, btn in enumerate(row):
            if btns[i].button(btn, key=f"calc_{btn}"):
                if btn == "=":
                    try:
                        result = eval(st.session_state.calc_expr)
                        st.session_state.calc_expr = str(result)
                    except:
                        st.session_state.calc_expr = "Error"
                elif btn == "C":
                    st.session_state.calc_expr = ""
                else:
                    st.session_state.calc_expr += btn
                st.rerun()
    st.write("Result: ", st.session_state.calc_expr)

def render_tariffs():
    require_permission("all")
    st.title("💰 Tariffs")
    st.info("Manage dispensing fees, markups, and medical aid tariffs.")
    dispensing_fee = st.number_input("Dispensing Fee ($)", min_value=0.0, value=5.0)
    markup_percent = st.number_input("Markup %", min_value=0.0, value=25.0)
    if st.button("Save Tariffs"):
        update_setting("dispensing_fee", str(dispensing_fee))
        update_setting("markup_percent", str(markup_percent))
        st.success("Tariffs saved")

def render_merge_patients():
    require_permission("patients_view")
    st.title("🔗 Merge Patient Files")
    with get_db_connection() as conn:
        patients = conn.execute("SELECT id, patient_id, first_name, last_name FROM patients").fetchall()
    pat_opts = {p[0]: f"{p[2]} {p[3]} ({p[1]})" for p in patients}
    source_id = st.selectbox("Source Patient (to merge FROM)", list(pat_opts.keys()), format_func=lambda x: pat_opts[x])
    target_id = st.selectbox("Target Patient (to merge INTO)", list(pat_opts.keys()), format_func=lambda x: pat_opts[x])
    if st.button("Merge Patients"):
        if source_id == target_id:
            st.error("Cannot merge a patient with itself")
        else:
            with get_db_connection() as conn:
                # Update prescriptions
                conn.execute("UPDATE prescriptions SET patient_id = ? WHERE patient_id = ?", (target_id, source_id))
                # Update sales
                conn.execute("UPDATE sales SET patient_id = ? WHERE patient_id = ?", (target_id, source_id))
                # Update loyalty points
                conn.execute("UPDATE loyalty_points SET patient_id = ? WHERE patient_id = ?", (target_id, source_id))
                # Delete source patient
                conn.execute("DELETE FROM patients WHERE id = ?", (source_id,))
                conn.commit()
            st.success("Patients merged successfully")
            st.rerun()

def render_quotation():
    require_permission("sales")
    st.title("📄 Quotation")
    with get_db_connection() as conn:
        patients = conn.execute("SELECT id, patient_id, first_name, last_name FROM patients").fetchall()
    pat_opts = {p[0]: f"{p[2]} {p[3]} ({p[1]})" for p in patients}
    patient_id = st.selectbox("Patient", list(pat_opts.keys()), format_func=lambda x: pat_opts[x])
    st.subheader("Add Items")
    if 'quotation_items' not in st.session_state:
        st.session_state.quotation_items = []
    with get_db_connection() as conn:
        medicines = conn.execute("SELECT id, name, unit_price FROM medicines").fetchall()
    med_opts = {m[0]: f"{m[1]} - ${m[2]:.2f}" for m in medicines}
    col1, col2, col3 = st.columns([2,1,1])
    with col1:
        med_id = st.selectbox("Medicine", list(med_opts.keys()), format_func=lambda x: med_opts[x], key="quot_med")
        med = next(m for m in medicines if m[0] == med_id)
    with col2:
        qty = st.number_input("Quantity", min_value=1, value=1, key="quot_qty")
    if st.button("Add Item"):
        st.session_state.quotation_items.append({
            "medicine_id": med_id,
            "name": med[1],
            "quantity": qty,
            "price": med[2],
            "total": med[2] * qty
        })
        st.rerun()
    if st.session_state.quotation_items:
        df = pd.DataFrame(st.session_state.quotation_items)
        st.dataframe(df)
        total = sum(item['total'] for item in st.session_state.quotation_items)
        st.write(f"**Total: ${total:.2f}**")
        valid_until = st.date_input("Valid Until", datetime.now().date() + timedelta(days=30))
        if st.button("Create Quotation"):
            quot_no = f"QT{datetime.now().strftime('%Y%m%d%H%M%S')}"
            items_json = json.dumps(st.session_state.quotation_items)
            with get_db_connection() as conn:
                conn.execute("""
                    INSERT INTO quotations (quotation_no, patient_id, items, total_amount, valid_until, created_by)
                    VALUES (?,?,?,?,?,?)
                """, (quot_no, patient_id, items_json, total, valid_until, st.session_state.user['id']))
                conn.commit()
            st.success(f"Quotation {quot_no} created")
            st.session_state.quotation_items = []
            # Generate PDF
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", "B", 16)
            pdf.cell(200, 10, "Quotation", ln=1, align='C')
            pdf.set_font("Arial", "", 12)
            pdf.cell(200, 10, f"Number: {quot_no}", ln=1)
            pdf.cell(200, 10, f"Date: {datetime.now().strftime('%Y-%m-%d')}", ln=1)
            pdf.cell(200, 10, f"Valid Until: {valid_until}", ln=1)
            pdf.ln(10)
            pdf.set_font("Arial", "B", 10)
            pdf.cell(80, 10, "Item", 1)
            pdf.cell(30, 10, "Qty", 1)
            pdf.cell(40, 10, "Price", 1)
            pdf.cell(40, 10, "Total", 1)
            pdf.ln()
            pdf.set_font("Arial", "", 10)
            for it in st.session_state.quotation_items:
                pdf.cell(80, 10, it['name'][:30], 1)
                pdf.cell(30, 10, str(it['quantity']), 1)
                pdf.cell(40, 10, f"${it['price']:.2f}", 1)
                pdf.cell(40, 10, f"${it['total']:.2f}", 1)
                pdf.ln()
            pdf.ln(5)
            pdf.cell(150, 10, "Total:", 0)
            pdf.cell(40, 10, f"${total:.2f}", 0)
            pdf_bytes = pdf.output(dest='S').encode('latin1')
            st.download_button("Download Quotation PDF", data=pdf_bytes, file_name=f"quotation_{quot_no}.pdf", mime="application/pdf")
            st.rerun()

def render_utilities():
    require_permission("all")
    st.title("🛠️ Utilities")
    st.markdown("""
    - **Printer Setup** – Configure printers for receipts and labels
    - **Change Password** – Update your login password
    - **Logout** – End your session
    - **Exit** – Simulated application exit
    """)
    if st.button("Go to Printer Setup"):
        st.session_state.page = "Printer Setup"
        st.rerun()
    if st.button("Change Password"):
        st.session_state.page = "Change Password"
        st.rerun()
    if st.button("Logout"):
        logout_user()
    if st.button("Exit"):
        st.warning("Exiting application... (simulated)")
        logout_user()

def render_license_expiry():
    require_permission("all")
    st.title("📅 License Expiry")
    # Simulate license expiry check
    expiry_date = date(2025, 12, 31)
    days_left = (expiry_date - date.today()).days
    if days_left < 0:
        st.error("⚠️ License has expired! Please renew immediately.")
    elif days_left < 30:
        st.warning(f"⚠️ License expires in {days_left} days. Please renew soon.")
    else:
        st.success(f"License is valid until {expiry_date} ({days_left} days remaining).")

# ==================== MAIN ====================
def main():
    st.set_page_config(
        page_title="Pharmacy Management System",
        page_icon="💊",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    st.markdown("""
    <meta name="description" content="Complete Pharmacy Management System with inventory, sales, prescriptions, AI assistant, and full reporting. Secure, accessible, and production-ready.">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <main role="main" style="display:block">
    """, unsafe_allow_html=True)

    if 'db_initialised' not in st.session_state:
        init_db()
        clear_all_lockouts()
        st.session_state.db_initialised = True

    qp = st.query_params
    if "unlock" in qp and qp["unlock"] == UNLOCK_SECRET:
        clear_all_lockouts()
        st.success("All login lockouts have been cleared. You can now log in.")
        st.stop()
    if "reset" in qp and qp["reset"] == RESET_SECRET:
        with get_db_connection() as conn:
            admin = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
            if admin:
                conn.execute("UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?",
                             (generate_password_hash(ADMIN_PASSWORD), admin[0]))
                conn.commit()
                st.success("Admin password has been reset. Please log in and change it immediately.")
                st.stop()
            else:
                st.error("Admin user not found.")

    if not st.session_state.get('logged_in'):
        st.title("🏥 Pharmacy Management System")
        col1, col2, col3 = st.columns([1,2,1])
        with col2:
            st.image("https://img.icons8.com/fluency/96/pill.png", width=100)
            st.markdown("<h2 style='text-align: center;'>Secure Login</h2>", unsafe_allow_html=True)
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.button("Login", type="primary", use_container_width=True):
                if username and password:
                    user = login_user(username, password)
                    if user:
                        st.session_state.logged_in = True
                        st.session_state.user = user
                        st.session_state.login_time = datetime.now()
                        if user.get('must_change_password'):
                            st.session_state.must_change_password = True
                        st.rerun()
                else:
                    st.warning("Please enter both username and password")
            st.caption("Default admin credentials: admin / Admin@123456 (change after first login)")
            st.caption("If locked out, add ?unlock=unlock123 to the URL")
        st.markdown("</main>", unsafe_allow_html=True)
        return

    check_session_timeout()
    if st.session_state.user.get('must_change_password'):
        st.title("🔐 Change Required Password")
        st.warning("You must change your default password before continuing.")
        new_pass = st.text_input("New Password", type="password")
        confirm_pass = st.text_input("Confirm Password", type="password")
        if st.button("Update Password"):
            if new_pass != confirm_pass:
                st.error("Passwords do not match")
            else:
                try:
                    change_password(st.session_state.user['id'], new_pass)
                    st.session_state.must_change_password = False
                    st.success("Password changed successfully. Please log in again.")
                    logout_user()
                except ValueError as e:
                    st.error(str(e))
        st.markdown("</main>", unsafe_allow_html=True)
        return

    st.sidebar.image("https://img.icons8.com/fluency/96/pill.png", width=80)
    st.sidebar.title(f"Welcome, {st.session_state.user['full_name']}")
    st.sidebar.write(f"Role: {st.session_state.user['role_name']}")

    # Define all menu items
    menu_items = {
        "Dashboard": "all",
        "Medicines": "medicines",
        "Inventory": "inventory",
        "Stocktake": "inventory",
        "Patients": "patients_view",
        "Medical Aid Societies": "patients_view",
        "Prescriptions": "prescriptions",
        "Sales & Billing": "sales",
        "Sales Returns": "sales",
        "Label Printing": "label_print",
        "Suppliers": "suppliers",
        "Reports": "reports",
        "Staff Management": "staff",
        "Notifications": "all",
        "Audit Logs": "audit",
        "Advanced Features": "advanced",
        "AI Assistant": "all",
        "Settings": "all",
        "Printer Setup": "all",
        "Change Password": "all",
        "Calculator": "all",
        "Tariffs": "all",
        "Merge Patients": "patients_view",
        "Quotation": "sales",
        "Utilities": "all",
        "License Expiry": "all"
    }

    user_perms = json.loads(st.session_state.user.get('permissions', '{}'))
    allowed_pages = []
    for page_name, required_perm in menu_items.items():
        if required_perm == "all" or user_perms.get('all') or user_perms.get(required_perm):
            allowed_pages.append(page_name)

    for page_name in allowed_pages:
        if st.sidebar.button(page_name, use_container_width=True):
            st.session_state.page = page_name

    if st.sidebar.button("🚪 Logout", use_container_width=True):
        logout_user()

    page = st.session_state.get('page', 'Dashboard')
    if page == "Dashboard":
        render_dashboard()
    elif page == "Medicines":
        render_medicines()
    elif page == "Inventory":
        render_inventory()
    elif page == "Stocktake":
        render_stocktake()
    elif page == "Patients":
        render_patients()
    elif page == "Medical Aid Societies":
        render_medical_aid_societies()
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
    elif page == "AI Assistant":
        render_ai_assistant()
    elif page == "Settings":
        render_settings()
    elif page == "Printer Setup":
        render_printer_setup()
    elif page == "Change Password":
        render_change_password()
    elif page == "Calculator":
        render_calculator()
    elif page == "Tariffs":
        render_tariffs()
    elif page == "Merge Patients":
        render_merge_patients()
    elif page == "Quotation":
        render_quotation()
    elif page == "Utilities":
        render_utilities()
    elif page == "License Expiry":
        render_license_expiry()
    else:
        render_dashboard()

    st.markdown("</main>", unsafe_allow_html=True)

# The change_password function is already defined; we reuse it.
def render_change_password():
    require_permission("all")
    st.title("🔑 Change Password")
    new_pass = st.text_input("New Password", type="password")
    confirm_pass = st.text_input("Confirm Password", type="password")
    if st.button("Update"):
        if new_pass != confirm_pass:
            st.error("Passwords do not match")
        else:
            try:
                change_password(st.session_state.user['id'], new_pass)
                st.success("Password changed. Please log in again.")
                logout_user()
            except ValueError as e:
                st.error(str(e))

if __name__ == "__main__":
    main()
    
