#!/usr/bin/env python
"""
Pharmacy Management System - Production Complete
Copyright © Isaac Madungwe 2026-2030
All features: AI Assistant, Inventory, Sales, Prescriptions, Patients, Suppliers,
Staff, Reports, Audit, Loyalty, Appointments, Drug Interactions, Forecasting.
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
from typing import Dict, Optional, List, Tuple
from difflib import get_close_matches
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
    print(f"Missing required library: {e}")
    print("Please run: pip install streamlit pandas bcrypt plotly fpdf qrcode python-barcode Pillow werkzeug numpy")
    sys.exit(1)

# ==================== CONFIGURATION ====================
DB_PATH = "pharmacy_management.db"
SESSION_TIMEOUT_SECONDS = 1800
LOGIN_ATTEMPT_LIMIT = 5
LOGIN_LOCKOUT_SECONDS = 300

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@123456")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== DATABASE ====================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db_connection() as conn:
        cur = conn.cursor()
        # ========== ALL TABLES ==========
        cur.execute("CREATE TABLE IF NOT EXISTS roles (id INTEGER PRIMARY KEY, name TEXT UNIQUE, permissions TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, full_name TEXT, email TEXT, role_id INTEGER, is_active INTEGER DEFAULT 1, must_change_password INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(role_id) REFERENCES roles(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY, name TEXT UNIQUE, description TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS medicines (id INTEGER PRIMARY KEY, name TEXT, generic_name TEXT, category_id INTEGER, barcode TEXT UNIQUE, manufacturer TEXT, unit_price REAL, reorder_level INTEGER DEFAULT 10, current_stock INTEGER DEFAULT 0, description TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(category_id) REFERENCES categories(id))")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_medicines_name ON medicines(name)")
        cur.execute("CREATE TABLE IF NOT EXISTS batches (id INTEGER PRIMARY KEY, medicine_id INTEGER, batch_number TEXT, quantity INTEGER, expiry_date DATE, purchase_price REAL, selling_price REAL, mrp REAL, supplier_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(medicine_id) REFERENCES medicines(id), FOREIGN KEY(supplier_id) REFERENCES suppliers(id))")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_batches_expiry ON batches(expiry_date)")
        cur.execute("CREATE TABLE IF NOT EXISTS inventory_transactions (id INTEGER PRIMARY KEY, medicine_id INTEGER, batch_id INTEGER, transaction_type TEXT, quantity INTEGER, reference_id TEXT, notes TEXT, created_by INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(medicine_id) REFERENCES medicines(id), FOREIGN KEY(batch_id) REFERENCES batches(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS patients (id INTEGER PRIMARY KEY, patient_id TEXT UNIQUE, first_name TEXT, last_name TEXT, date_of_birth DATE, gender TEXT, phone TEXT, email TEXT, address TEXT, insurance_provider TEXT, insurance_number TEXT, blood_group TEXT, allergies TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        cur.execute("CREATE TABLE IF NOT EXISTS medical_history (id INTEGER PRIMARY KEY, patient_id INTEGER, condition TEXT, diagnosis_date DATE, notes TEXT, FOREIGN KEY(patient_id) REFERENCES patients(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS prescriptions (id INTEGER PRIMARY KEY, prescription_number TEXT UNIQUE, patient_id INTEGER, doctor_name TEXT, prescribed_date DATE, expiry_date DATE, status TEXT DEFAULT 'pending', pharmacist_notes TEXT, approved_by INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(patient_id) REFERENCES patients(id), FOREIGN KEY(approved_by) REFERENCES users(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS prescription_items (id INTEGER PRIMARY KEY, prescription_id INTEGER, medicine_id INTEGER, dosage TEXT, duration TEXT, instructions TEXT, quantity INTEGER, FOREIGN KEY(prescription_id) REFERENCES prescriptions(id), FOREIGN KEY(medicine_id) REFERENCES medicines(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS sales (id INTEGER PRIMARY KEY, invoice_number TEXT UNIQUE, patient_id INTEGER, user_id INTEGER, total_amount REAL, discount REAL DEFAULT 0, tax REAL DEFAULT 0, net_amount REAL, payment_method TEXT, payment_status TEXT DEFAULT 'completed', loyalty_points_earned INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(patient_id) REFERENCES patients(id), FOREIGN KEY(user_id) REFERENCES users(id))")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(created_at)")
        cur.execute("CREATE TABLE IF NOT EXISTS sale_items (id INTEGER PRIMARY KEY, sale_id INTEGER, medicine_id INTEGER, batch_id INTEGER, quantity INTEGER, unit_price REAL, total REAL, FOREIGN KEY(sale_id) REFERENCES sales(id), FOREIGN KEY(medicine_id) REFERENCES medicines(id), FOREIGN KEY(batch_id) REFERENCES batches(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS sales_returns (id INTEGER PRIMARY KEY, original_sale_id INTEGER, sale_item_id INTEGER, quantity_returned INTEGER, refund_amount REAL, reason TEXT, created_by INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(original_sale_id) REFERENCES sales(id), FOREIGN KEY(sale_item_id) REFERENCES sale_items(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS suppliers (id INTEGER PRIMARY KEY, name TEXT, contact_person TEXT, phone TEXT, email TEXT, address TEXT, gst_number TEXT, payment_terms TEXT, is_active INTEGER DEFAULT 1)")
        cur.execute("CREATE TABLE IF NOT EXISTS purchase_orders (id INTEGER PRIMARY KEY, po_number TEXT UNIQUE, supplier_id INTEGER, order_date DATE, expected_delivery DATE, total_amount REAL, status TEXT DEFAULT 'pending', created_by INTEGER, FOREIGN KEY(supplier_id) REFERENCES suppliers(id), FOREIGN KEY(created_by) REFERENCES users(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS staff_attendance (id INTEGER PRIMARY KEY, user_id INTEGER, date DATE, check_in TIME, check_out TIME, status TEXT DEFAULT 'present', UNIQUE(user_id, date), FOREIGN KEY(user_id) REFERENCES users(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY, title TEXT, message TEXT, type TEXT, is_read INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        cur.execute("CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY, user_id INTEGER, action TEXT, details TEXT, ip_address TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id))")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id)")
        cur.execute("CREATE TABLE IF NOT EXISTS loyalty_points (id INTEGER PRIMARY KEY, patient_id INTEGER, points INTEGER DEFAULT 0, redeemed INTEGER DEFAULT 0, FOREIGN KEY(patient_id) REFERENCES patients(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS appointments (id INTEGER PRIMARY KEY, patient_id INTEGER, appointment_date DATE, appointment_time TIME, purpose TEXT, status TEXT DEFAULT 'scheduled', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(patient_id) REFERENCES patients(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS drug_interactions (id INTEGER PRIMARY KEY, medicine1_id INTEGER, medicine2_id INTEGER, severity TEXT, description TEXT, FOREIGN KEY(medicine1_id) REFERENCES medicines(id), FOREIGN KEY(medicine2_id) REFERENCES medicines(id))")
        cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        # ========== DEFAULT DATA ==========
        roles = [("Admin", '{"all":true}'), ("Manager", '{"medicines":true,"inventory":true,"suppliers":true,"reports":true,"staff":true,"audit":true}'), ("Pharmacist", '{"prescriptions":true,"inventory_view":true,"sales_view":true,"label_print":true}'), ("Cashier", '{"sales":true,"patients_view":true}')]
        for name, perms in roles:
            cur.execute("INSERT OR IGNORE INTO roles (name, permissions) VALUES (?,?)", (name, perms))
        admin_role = cur.execute("SELECT id FROM roles WHERE name='Admin'").fetchone()
        if admin_role and not cur.execute("SELECT id FROM users WHERE username='admin'").fetchone():
            cur.execute("INSERT INTO users (username, password_hash, full_name, email, role_id, must_change_password) VALUES (?,?,?,?,?,1)", ("admin", generate_password_hash(ADMIN_PASSWORD), "System Administrator", "admin@pharmacy.com", admin_role[0]))
        categories = ["Antibiotics","Analgesics","Antipyretics","Vitamins","Antihistamines","Dermatologicals"]
        for cat in categories:
            cur.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat,))
        default_settings = {"pharmacy_name":"HealthPlus Pharmacy","pharmacy_address":"123 Main Street","pharmacy_phone":"+1 234 567 8900","pharmacy_email":"info@healthplus.com","tax_number":"TAX123456","pharmacist_license":"PHARM-7890","receipt_footer":"Thank you!","loyalty_rate":"5","gst_rate":"5","cgst_rate":"2.5","sgst_rate":"2.5"}
        for key,val in default_settings.items():
            cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)", (key, val))
        conn.commit()
        # No default drug interaction inserted (to avoid foreign key errors). User can add via UI.

init_db()

# ==================== HELPER FUNCTIONS ====================
def get_settings_dict():
    with get_db_connection() as conn:
        return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings").fetchall()}

def update_setting(key, value):
    with get_db_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?,?,CURRENT_TIMESTAMP)", (key, value))
        conn.commit()

def log_audit(user_id, action, details=""):
    try:
        with get_db_connection() as conn:
            conn.execute("INSERT INTO audit_logs (user_id, action, details) VALUES (?,?,?)", (user_id, action, details))
            conn.commit()
    except: pass

def require_permission(perm):
    if not st.session_state.get('logged_in'): st.error("Please log in."); st.stop()
    perms = json.loads(st.session_state.user.get('permissions','{}'))
    if perms.get('all') or perms.get(perm): return True
    st.error(f"Permission '{perm}' required."); st.stop()

def get_low_stock():
    with get_db_connection() as conn:
        rows = conn.execute("SELECT id,name,current_stock,reorder_level FROM medicines WHERE current_stock <= reorder_level").fetchall()
        return pd.DataFrame([{"id":r[0],"name":r[1],"stock":r[2],"reorder":r[3]} for r in rows])

def get_expiring(days=30):
    exp = (datetime.now() + timedelta(days=days)).date().isoformat()
    with get_db_connection() as conn:
        rows = conn.execute("SELECT b.id, m.name, b.batch_number, b.expiry_date, b.quantity FROM batches b JOIN medicines m ON b.medicine_id=m.id WHERE b.expiry_date <= ? AND b.quantity>0 ORDER BY b.expiry_date", (exp,)).fetchall()
        return pd.DataFrame([{"id":r[0],"name":r[1],"batch":r[2],"expiry":r[3],"qty":r[4]} for r in rows])

def get_best_batch(medicine_id, needed):
    with get_db_connection() as conn:
        batches = conn.execute("SELECT id, quantity, selling_price FROM batches WHERE medicine_id=? AND quantity>0 AND expiry_date>date('now') ORDER BY expiry_date ASC", (medicine_id,)).fetchall()
    res = []
    rem = needed
    for b in batches:
        take = min(b[1], rem)
        if take>0: res.append({"batch_id":b[0],"quantity":take,"price":b[2]}); rem -= take
        if rem==0: break
    if rem>0: raise ValueError(f"Insufficient stock")
    return res

def generate_invoice_pdf(data):
    pdf = FPDF(); pdf.add_page()
    pdf.set_font("Arial","B",16)
    s = get_settings_dict()
    pdf.cell(200,10, s.get("pharmacy_name","Pharmacy"), ln=1, align='C')
    pdf.set_font("Arial","",10)
    pdf.cell(200,5, s.get("pharmacy_address",""), ln=1, align='C')
    pdf.cell(200,5, f"Phone: {s.get('pharmacy_phone','')}", ln=1, align='C')
    pdf.ln(10)
    pdf.set_font("Arial","B",12)
    pdf.cell(200,10, f"Invoice: {data['invoice_number']}", ln=1)
    pdf.cell(200,10, f"Date: {data['date']}", ln=1)
    pdf.cell(200,10, f"Patient: {data.get('patient_name','Walk-in')}", ln=1)
    pdf.ln(5)
    pdf.set_font("Arial","B",10)
    pdf.cell(80,10,"Item",1); pdf.cell(30,10,"Qty",1); pdf.cell(40,10,"Price",1); pdf.cell(40,10,"Total",1); pdf.ln()
    pdf.set_font("Arial","",10)
    for it in data['items']:
        pdf.cell(80,10, it['name'][:30],1); pdf.cell(30,10, str(it['quantity']),1); pdf.cell(40,10, f"${it['price']:.2f}",1); pdf.cell(40,10, f"${it['total']:.2f}",1); pdf.ln()
    pdf.ln(5)
    pdf.set_font("Arial","B",10)
    pdf.cell(150,10,"Total:",0); pdf.cell(40,10, f"${data['total']:.2f}",0); pdf.ln()
    pdf.cell(150,10,"Discount:",0); pdf.cell(40,10, f"${data.get('discount',0):.2f}",0); pdf.ln()
    pdf.cell(150,10,"Tax (GST):",0); pdf.cell(40,10, f"${data.get('tax',0):.2f}",0); pdf.ln()
    pdf.cell(150,10,"Net Amount:",0); pdf.cell(40,10, f"${data['net_amount']:.2f}",0); pdf.ln(10)
    pdf.cell(200,10, s.get("receipt_footer","Thank you!"), ln=1, align='C')
    return pdf.output(dest='S').encode('latin1')

def generate_barcode(data):
    try:
        code128 = barcode.get_barcode_class('code128')
        buf = io.BytesIO()
        code128(data, writer=ImageWriter()).write(buf)
        buf.seek(0)
        return Image.open(buf)
    except: return Image.new('RGB',(300,100),'white')

def generate_qr(data):
    qr = qrcode.QRCode(box_size=5,border=2); qr.add_data(data)
    return qr.make_image(fill_color="black",back_color="white")

def create_notification(title, message, type_="info"):
    with get_db_connection() as conn:
        conn.execute("INSERT INTO notifications (title, message, type) VALUES (?,?,?)", (title, message, type_))
        conn.commit()

def stock_forecast(medicine_id, days=30):
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT DATE(created_at) as d, SUM(si.quantity) as qty
            FROM sale_items si JOIN sales s ON si.sale_id=s.id
            WHERE si.medicine_id=? AND s.created_at >= date('now','-30 days')
            GROUP BY DATE(s.created_at)
        """, (medicine_id,)).fetchall()
    if len(rows)<2: return None
    x = list(range(len(rows)))
    y = [r[1] for r in rows]
    try:
        z = np.polyfit(x, y, 1)
        forecast = z[0] * days + z[1]
        return max(0, int(forecast))
    except: return None

# ==================== AUTHENTICATION ====================
def login_user(username, password):
    with get_db_connection() as conn:
        lock = conn.execute("SELECT value FROM settings WHERE key=? AND value > datetime('now')", (f"lockout_{username}",)).fetchone()
        if lock: st.error("Account locked."); return None
        user = conn.execute("SELECT u.id,u.username,u.password_hash,u.full_name,u.email,u.role_id,u.must_change_password,r.name as role_name,r.permissions FROM users u JOIN roles r ON u.role_id=r.id WHERE u.username=? AND u.is_active=1", (username,)).fetchone()
        if user and check_password_hash(user[2], password):
            conn.execute("DELETE FROM settings WHERE key=?", (f"failures_{username}",))
            conn.commit()
            log_audit(user[0], "LOGIN", f"User {username} logged in")
            return {"id":user[0],"username":user[1],"full_name":user[3],"email":user[4],"role_id":user[5],"must_change_password":user[6],"role_name":user[7],"permissions":user[8]}
        else:
            fail = conn.execute("SELECT value FROM settings WHERE key=?", (f"failures_{username}",)).fetchone()
            fail_count = int(fail[0]) if fail else 0
            fail_count+=1
            conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (f"failures_{username}", str(fail_count)))
            if fail_count>=LOGIN_ATTEMPT_LIMIT:
                lock_until = (datetime.now()+timedelta(seconds=LOGIN_LOCKOUT_SECONDS)).isoformat()
                conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (f"lockout_{username}", lock_until))
            conn.commit()
            return None

def change_password(user_id, new_password):
    if len(new_password)<8 or not re.search(r"[A-Z]",new_password) or not re.search(r"[a-z]",new_password) or not re.search(r"[0-9]",new_password):
        raise ValueError("Password must be 8+ chars with upper, lower, digit.")
    with get_db_connection() as conn:
        conn.execute("UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?", (generate_password_hash(new_password), user_id))
        conn.commit()
        log_audit(user_id, "PASSWORD_CHANGE", "")

def logout_user():
    if st.session_state.get('user'): log_audit(st.session_state.user['id'], "LOGOUT", "")
    st.session_state.clear()
    st.session_state.logged_in=False
    st.rerun()

def check_session_timeout():
    if 'login_time' in st.session_state:
        if (datetime.now()-st.session_state.login_time).total_seconds() > SESSION_TIMEOUT_SECONDS:
            st.warning("Session expired."); logout_user(); st.stop()
    else: st.session_state.login_time = datetime.now()

# ==================== AI ASSISTANT ====================
MED_KNOWLEDGE = {
    "fever": {"meds":["Paracetamol","Ibuprofen"],"dosage":"500mg every 6h","warning":"Max 4g/day"},
    "cold": {"meds":["Cetirizine","Pseudoephedrine"],"dosage":"10mg daily","warning":"May cause drowsiness"},
    "cough": {"meds":["Dextromethorphan","Guaifenesin"],"dosage":"10-20mg every 4h","warning":"Drink water"},
    "headache": {"meds":["Aspirin","Ibuprofen"],"dosage":"400mg every 6h","warning":"Take with food"},
}

def ai_response(q):
    q = q.lower()
    if "stock" in q or "available" in q:
        with get_db_connection() as conn:
            meds = conn.execute("SELECT name, current_stock FROM medicines WHERE current_stock>0 LIMIT 5").fetchall()
        return "📦 Stock:\n"+ "\n".join([f"{m[0]}: {m[1]} units" for m in meds]) if meds else "No stock."
    if "expiring" in q:
        exp = get_expiring(30)
        return "⚠️ Expiring soon:\n"+ "\n".join([f"{r['name']} (batch {r['batch']}) expires {r['expiry']}" for _,r in exp.iterrows()]) if not exp.empty else "No expiring products."
    if "low stock" in q:
        low = get_low_stock()
        return "⚠️ Low stock:\n"+ "\n".join([f"{r['name']}: {r['stock']} units" for _,r in low.iterrows()]) if not low.empty else "Stock levels OK."
    for sym,info in MED_KNOWLEDGE.items():
        if sym in q:
            return f"🩺 For {sym}:\n- Medicines: {', '.join(info['meds'])}\n- Dosage: {info['dosage']}\n- Warning: {info['warning']}\n\n*Consult doctor.*"
    if "help" in q:
        return "Ask about: fever, cold, stock, expiring, low stock, or drug interactions."
    return "I can help with medicine suggestions, stock alerts, expiries. Try 'fever' or 'low stock'."

# ==================== PAGE FUNCTIONS ====================
def render_login_page():
    st.set_page_config(page_title="Pharmacy System", layout="wide")
    st.title("🏥 Pharmacy Management System")
    c1,c2,c3 = st.columns([1,2,1])
    with c2:
        st.image("https://img.icons8.com/fluency/96/pill.png", width=100)
        st.subheader("Secure Login")
        uname = st.text_input("Username")
        pwd = st.text_input("Password", type="password")
        if st.button("Login", type="primary"):
            if uname and pwd:
                user = login_user(uname, pwd)
                if user:
                    st.session_state.logged_in=True
                    st.session_state.user=user
                    st.session_state.login_time=datetime.now()
                    if user.get('must_change_password'):
                        st.session_state.must_change_password=True
                    st.rerun()
                else:
                    st.error("Invalid credentials")
            else:
                st.warning("Enter both fields")

def render_change_password():
    st.title("🔐 Change Required Password")
    st.warning("You must change your default password.")
    new = st.text_input("New Password", type="password")
    conf = st.text_input("Confirm", type="password")
    if st.button("Update"):
        if new!=conf:
            st.error("Passwords do not match")
        else:
            try:
                change_password(st.session_state.user['id'], new)
                st.session_state.must_change_password=False
                st.success("Password changed. Please log in again.")
                logout_user()
            except ValueError as e:
                st.error(str(e))

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
    if not low.empty: st.warning(f"⚠️ Low stock: {len(low)} medicines")
    if not exp.empty: st.error(f"⚠️ Expiring soon: {len(exp)} batches")
    with get_db_connection() as conn:
        trend = conn.execute("SELECT DATE(created_at) as d, SUM(net_amount) as s FROM sales WHERE created_at >= DATE('now','-7 days') GROUP BY DATE(created_at) ORDER BY d").fetchall()
    if trend:
        df = pd.DataFrame([{"date":r[0],"sales":r[1]} for r in trend])
        fig = px.line(df, x='date', y='sales', title='Last 7 Days Sales')
        st.plotly_chart(fig, use_container_width=True)
    with get_db_connection() as conn:
        top = conn.execute("SELECT m.name, SUM(si.quantity) as sold FROM sale_items si JOIN medicines m ON si.medicine_id=m.id GROUP BY si.medicine_id ORDER BY sold DESC LIMIT 5").fetchall()
    if top:
        df_top = pd.DataFrame([{"name":r[0],"sold":r[1]} for r in top])
        fig2 = px.bar(df_top, x='name', y='sold', title='Top Selling Medicines')
        st.plotly_chart(fig2, use_container_width=True)

def render_medicines():
    require_permission("medicines")
    st.title("💊 Medicines")
    tab1,tab2,tab3 = st.tabs(["List","Add/Edit","Categories"])
    with tab1:
        search = st.text_input("Search")
        page = st.number_input("Page",1,value=1)
        per=20
        off=(page-1)*per
        with get_db_connection() as conn:
            if search:
                count = conn.execute("SELECT COUNT(*) FROM medicines WHERE name LIKE ? OR generic_name LIKE ?", (f"%{search}%",f"%{search}%")).fetchone()[0]
                rows = conn.execute("SELECT m.*, c.name as cat FROM medicines m LEFT JOIN categories c ON m.category_id=c.id WHERE m.name LIKE ? OR m.generic_name LIKE ? LIMIT ? OFFSET ?", (f"%{search}%",f"%{search}%",per,off)).fetchall()
            else:
                count = conn.execute("SELECT COUNT(*) FROM medicines").fetchone()[0]
                rows = conn.execute("SELECT m.*, c.name as cat FROM medicines m LEFT JOIN categories c ON m.category_id=c.id LIMIT ? OFFSET ?", (per,off)).fetchall()
        st.write(f"Total: {count}")
        for r in rows:
            col1,col2,col3,col4 = st.columns([3,1,1,1])
            col1.write(f"**{r['name']}** (Stock: {r['current_stock']})")
            if col2.button("✏️", key=f"edit_{r['id']}"):
                st.session_state.edit_medicine = dict(r)
            if col3.button("🗑️", key=f"del_{r['id']}"):
                with get_db_connection() as conn2:
                    conn2.execute("DELETE FROM medicines WHERE id=?", (r['id'],))
                    conn2.commit()
                st.rerun()
            if col4.button("🏷️", key=f"barcode_{r['id']}"):
                img = generate_barcode(r['barcode'] or str(r['id']))
                st.image(img, width=100)
    with tab2:
        med = st.session_state.get('edit_medicine', {})
        with get_db_connection() as conn:
            cats = conn.execute("SELECT id,name FROM categories").fetchall()
        cat_opts = {c[0]:c[1] for c in cats}
        name = st.text_input("Name", med.get('name',''))
        generic = st.text_input("Generic", med.get('generic_name',''))
        cat = st.selectbox("Category", list(cat_opts.keys()), format_func=lambda x:cat_opts[x], index=0 if not med else next((i for i,c in enumerate(cats) if c[0]==med.get('category_id')),0))
        bcode = st.text_input("Barcode", med.get('barcode',''))
        manuf = st.text_input("Manufacturer", med.get('manufacturer',''))
        price = st.number_input("Price ($)",0.0,value=float(med.get('unit_price',0)))
        reorder = st.number_input("Reorder Level",0,value=int(med.get('reorder_level',10)))
        stock = st.number_input("Stock",0,value=int(med.get('current_stock',0)))
        desc = st.text_area("Description", med.get('description',''))
        if st.button("Save"):
            with get_db_connection() as conn:
                if 'edit_medicine' in st.session_state:
                    conn.execute("UPDATE medicines SET name=?, generic_name=?, category_id=?, barcode=?, manufacturer=?, unit_price=?, reorder_level=?, current_stock=?, description=? WHERE id=?", (name,generic,cat,bcode,manuf,price,reorder,stock,desc,med['id']))
                    del st.session_state.edit_medicine
                else:
                    conn.execute("INSERT INTO medicines (name,generic_name,category_id,barcode,manufacturer,unit_price,reorder_level,current_stock,description) VALUES (?,?,?,?,?,?,?,?,?)", (name,generic,cat,bcode,manuf,price,reorder,stock,desc))
                conn.commit()
            st.success("Saved"); st.rerun()
    with tab3:
        new_cat = st.text_input("New Category")
        if st.button("Add Category") and new_cat:
            with get_db_connection() as conn:
                conn.execute("INSERT INTO categories (name) VALUES (?) ON CONFLICT DO NOTHING", (new_cat,))
                conn.commit()
            st.rerun()
        with get_db_connection() as conn:
            for c in conn.execute("SELECT id,name FROM categories").fetchall():
                col1,col2 = st.columns([3,1])
                col1.write(c[1])
                if col2.button("Delete", key=f"delcat_{c[0]}"):
                    conn.execute("DELETE FROM categories WHERE id=?", (c[0],))
                    conn.commit()
                    st.rerun()

def render_inventory():
    require_permission("inventory")
    st.title("📦 Inventory")
    tab1,tab2 = st.tabs(["Stock In/Out","Batches"])
    with tab1:
        with get_db_connection() as conn:
            meds = conn.execute("SELECT id,name FROM medicines").fetchall()
        med_opts = {m[0]:m[1] for m in meds}
        med_id = st.selectbox("Medicine", list(med_opts.keys()), format_func=lambda x:med_opts[x])
        trans = st.selectbox("Type", ["Stock In","Stock Out"])
        qty = st.number_input("Quantity",1)
        notes = st.text_area("Notes")
        if trans=="Stock In":
            batch = st.text_input("Batch Number")
            exp = st.date_input("Expiry", datetime.now()+timedelta(days=365))
            pp = st.number_input("Purchase Price",0.0)
            sp = st.number_input("Selling Price",0.0)
            if st.button("Add Stock"):
                with get_db_connection() as conn:
                    conn.execute("INSERT INTO batches (medicine_id,batch_number,quantity,expiry_date,purchase_price,selling_price) VALUES (?,?,?,?,?,?)", (med_id,batch,qty,exp,pp,sp))
                    conn.execute("UPDATE medicines SET current_stock = current_stock + ? WHERE id=?", (qty,med_id))
                    conn.commit()
                st.success("Stock added"); st.rerun()
        else:
            if st.button("Deduct Stock"):
                try:
                    batches = get_best_batch(med_id, qty)
                    with get_db_connection() as conn:
                        for b in batches:
                            conn.execute("UPDATE batches SET quantity = quantity - ? WHERE id=?", (b['quantity'], b['batch_id']))
                        conn.execute("UPDATE medicines SET current_stock = current_stock - ? WHERE id=?", (qty, med_id))
                        conn.commit()
                    st.success(f"Stock out using {len(batches)} batches")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
    with tab2:
        with get_db_connection() as conn:
            batches = conn.execute("SELECT b.*, m.name as med FROM batches b JOIN medicines m ON b.medicine_id=m.id ORDER BY b.expiry_date").fetchall()
        if batches:
            df = pd.DataFrame([dict(r) for r in batches])
            st.dataframe(df[['med','batch_number','quantity','expiry_date','purchase_price','selling_price']])

def render_patients():
    require_permission("patients_view")
    st.title("👥 Patients")
    tab1,tab2 = st.tabs(["List","Register"])
    with tab1:
        search = st.text_input("Search")
        with get_db_connection() as conn:
            if search:
                rows = conn.execute("SELECT * FROM patients WHERE first_name LIKE ? OR last_name LIKE ? OR patient_id LIKE ? OR phone LIKE ?", (f"%{search}%",f"%{search}%",f"%{search}%",f"%{search}%")).fetchall()
            else:
                rows = conn.execute("SELECT * FROM patients LIMIT 50").fetchall()
        for r in rows:
            with st.expander(f"{r['first_name']} {r['last_name']} ({r['patient_id']})"):
                col1,col2 = st.columns(2)
                col1.write(f"📞 {r['phone']}"); col1.write(f"📧 {r['email']}")
                col2.write(f"🩸 {r['blood_group']}"); col2.write(f"⚠️ {r['allergies'] or 'None'}")
    with tab2:
        col1,col2 = st.columns(2)
        with col1:
            first = st.text_input("First Name")
            last = st.text_input("Last Name")
            dob = st.date_input("DOB", datetime.now()-timedelta(days=365*30))
            gender = st.selectbox("Gender", ["Male","Female","Other"])
            phone = st.text_input("Phone")
            email = st.text_input("Email")
        with col2:
            address = st.text_area("Address")
            ins_prov = st.text_input("Insurance Provider")
            ins_num = st.text_input("Insurance Number")
            blood = st.selectbox("Blood Group", ["A+","A-","B+","B-","O+","O-","AB+","AB-"])
            allergies = st.text_area("Allergies")
        if st.button("Register"):
            if first and last:
                pid = f"PAT{datetime.now().strftime('%Y%m%d%H%M%S')}"
                with get_db_connection() as conn:
                    conn.execute("INSERT INTO patients (patient_id,first_name,last_name,date_of_birth,gender,phone,email,address,insurance_provider,insurance_number,blood_group,allergies) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (pid,first,last,dob,gender,phone,email,address,ins_prov,ins_num,blood,allergies))
                    conn.commit()
                st.success(f"Registered ID: {pid}")
                st.rerun()

def render_prescriptions():
    require_permission("prescriptions")
    st.title("📋 Prescriptions")
    tab1,tab2 = st.tabs(["Pending","New"])
    with tab1:
        with get_db_connection() as conn:
            pending = conn.execute("SELECT p.*, pat.first_name, pat.last_name FROM prescriptions p JOIN patients pat ON p.patient_id=pat.id WHERE p.status='pending'").fetchall()
        for p in pending:
            with st.expander(f"#{p['prescription_number']} - {p['first_name']} {p['last_name']}"):
                st.write(f"Doctor: {p['doctor_name']}, Date: {p['prescribed_date']}")
                items = conn.execute("SELECT pi.*, m.name, m.current_stock FROM prescription_items pi JOIN medicines m ON pi.medicine_id=m.id WHERE pi.prescription_id=?", (p['id'],)).fetchall()
                stock_ok = True
                for it in items:
                    st.write(f"- {it['name']}: Qty {it['quantity']}, Stock {it['current_stock']}")
                    if it['quantity'] > it['current_stock']: stock_ok=False; st.error(f"Stock insufficient for {it['name']}")
                notes = st.text_area("Pharmacist Notes", key=f"notes_{p['id']}")
                col1,col2 = st.columns(2)
                if col1.button("Approve", key=f"app_{p['id']}"):
                    if not stock_ok: st.error("Cannot approve: insufficient stock")
                    else:
                        with get_db_connection() as conn2:
                            conn2.execute("UPDATE prescriptions SET status='approved', pharmacist_notes=?, approved_by=? WHERE id=?", (notes, st.session_state.user['id'], p['id']))
                            conn2.commit()
                        st.success("Approved"); st.rerun()
                if col2.button("Reject", key=f"rej_{p['id']}"):
                    with get_db_connection() as conn2:
                        conn2.execute("UPDATE prescriptions SET status='rejected' WHERE id=?", (p['id'],))
                        conn2.commit()
                    st.rerun()
    with tab2:
        st.subheader("New Prescription")
        with get_db_connection() as conn:
            patients = conn.execute("SELECT id, patient_id, first_name, last_name FROM patients").fetchall()
        pat_opts = {p[0]: f"{p[2]} {p[3]} ({p[1]})" for p in patients}
        patient_id = st.selectbox("Patient", list(pat_opts.keys()), format_func=lambda x:pat_opts[x])
        doctor = st.text_input("Doctor Name")
        pres_date = st.date_input("Prescribed Date", datetime.now().date())
        exp_date = st.date_input("Expiry Date", datetime.now().date()+timedelta(days=30))
        with get_db_connection() as conn:
            all_meds = conn.execute("SELECT id,name FROM medicines").fetchall()
        med_opts = {m[0]:m[1] for m in all_meds}
        if 'pres_items' not in st.session_state: st.session_state.pres_items = []
        col1,col2,col3,col4 = st.columns([2,1,2,1])
        with col1: med_sel = st.selectbox("Medicine", list(med_opts.keys()), format_func=lambda x:med_opts[x], key="med_sel")
        with col2: qty = st.number_input("Qty",1, key="qty_sel")
        with col3: dosage = st.text_input("Dosage", key="dosage_sel")
        with col4: dur = st.text_input("Duration", key="dur_sel")
        if st.button("Add Medicine"):
            st.session_state.pres_items.append({"medicine_id":med_sel,"name":med_opts[med_sel],"quantity":qty,"dosage":dosage,"duration":dur})
            st.rerun()
        for idx,it in enumerate(st.session_state.pres_items):
            st.write(f"{idx+1}. {it['name']} - Qty {it['quantity']}, Dosage {it['dosage']}")
            if st.button(f"Remove {idx}", key=f"rem_{idx}"):
                st.session_state.pres_items.pop(idx); st.rerun()
        if st.button("Save Prescription"):
            if patient_id:
                pres_num = f"RX{datetime.now().strftime('%Y%m%d%H%M%S')}"
                with get_db_connection() as conn:
                    conn.execute("INSERT INTO prescriptions (prescription_number,patient_id,doctor_name,prescribed_date,expiry_date,status) VALUES (?,?,?,?,?,'pending')", (pres_num,patient_id,doctor,pres_date,exp_date))
                    pres_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    for it in st.session_state.pres_items:
                        conn.execute("INSERT INTO prescription_items (prescription_id,medicine_id,dosage,duration,instructions,quantity) VALUES (?,?,?,?,?,?)", (pres_id, it['medicine_id'], it['dosage'], it['duration'], it['dosage'], it['quantity']))
                    conn.commit()
                st.session_state.pres_items = []
                st.success(f"Prescription {pres_num} created"); st.rerun()

def render_sales_billing():
    require_permission("sales")
    st.title("💰 Sales & Billing")
    if 'cart' not in st.session_state: st.session_state.cart = []
    col1,col2 = st.columns([2,1])
    with col1:
        with get_db_connection() as conn:
            meds = conn.execute("SELECT id,name,unit_price,current_stock FROM medicines WHERE current_stock>0").fetchall()
        if not meds: st.warning("No medicines in stock")
        else:
            med_opts = {m[0]: f"{m[1]} - ${m[2]:.2f}" for m in meds}
            med_id = st.selectbox("Medicine", list(med_opts.keys()), format_func=lambda x:med_opts[x])
            med = next(m for m in meds if m[0]==med_id)
            qty = st.number_input("Quantity",1, med[3])
            if st.button("Add to Cart"):
                try:
                    batches = get_best_batch(med_id, qty)
                    st.session_state.cart.append({"medicine_id":med_id,"name":med[1],"quantity":qty,"unit_price":med[2],"total":med[2]*qty,"batches":batches})
                    st.rerun()
                except ValueError as e: st.error(str(e))
    with col2:
        if st.session_state.cart:
            df = pd.DataFrame([{"Item":c['name'],"Qty":c['quantity'],"Price":c['unit_price'],"Total":c['total']} for c in st.session_state.cart])
            st.dataframe(df)
            subtotal = sum(c['total'] for c in st.session_state.cart)
            discount = st.number_input("Discount ($)",0.0, value=0.0)
            settings = get_settings_dict()
            gst_rate = float(settings.get("gst_rate",5))
            tax = (subtotal-discount)*gst_rate/100
            net = subtotal - discount + tax
            st.write(f"**Subtotal: ${subtotal:.2f}**")
            st.write(f"**Tax (GST {gst_rate}%): ${tax:.2f}**")
            st.write(f"**Net: ${net:.2f}**")
            patient_search = st.text_input("Patient ID (optional)")
            payment = st.selectbox("Payment Method", ["Cash","Card","Insurance","UPI"])
            if st.button("Complete Sale"):
                with get_db_connection() as conn:
                    patient_id = None
                    if patient_search:
                        p = conn.execute("SELECT id FROM patients WHERE patient_id=?", (patient_search,)).fetchone()
                        if p: patient_id = p[0]
                    inv_no = f"INV{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    loyalty = int(net * 0.05)
                    conn.execute("INSERT INTO sales (invoice_number,patient_id,user_id,total_amount,discount,tax,net_amount,payment_method,loyalty_points_earned) VALUES (?,?,?,?,?,?,?,?,?)", (inv_no,patient_id,st.session_state.user['id'],subtotal,discount,tax,net,payment,loyalty))
                    sale_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    for item in st.session_state.cart:
                        for b in item['batches']:
                            conn.execute("INSERT INTO sale_items (sale_id,medicine_id,batch_id,quantity,unit_price,total) VALUES (?,?,?,?,?,?)", (sale_id,item['medicine_id'],b['batch_id'],b['quantity'],item['unit_price'],b['quantity']*item['unit_price']))
                            conn.execute("UPDATE batches SET quantity = quantity - ? WHERE id=?", (b['quantity'], b['batch_id']))
                        conn.execute("UPDATE medicines SET current_stock = current_stock - ? WHERE id=?", (item['quantity'], item['medicine_id']))
                    if patient_id:
                        conn.execute("INSERT INTO loyalty_points (patient_id, points, redeemed) VALUES (?,?,0) ON CONFLICT(patient_id) DO UPDATE SET points = points + excluded.points", (patient_id, loyalty))
                    conn.commit()
                receipt = {"invoice_number":inv_no,"date":datetime.now().strftime("%Y-%m-%d %H:%M"),"patient_name":patient_search or "Walk-in","items":[{"name":c['name'],"quantity":c['quantity'],"price":c['unit_price'],"total":c['total']} for c in st.session_state.cart],"total":subtotal,"discount":discount,"tax":tax,"net_amount":net}
                pdf_bytes = generate_invoice_pdf(receipt)
                st.success(f"Sale complete! Invoice: {inv_no}")
                st.download_button("Download Receipt", data=pdf_bytes, file_name=f"{inv_no}.pdf", mime="application/pdf")
                st.session_state.cart = []; st.rerun()
        else: st.info("Cart empty")

def render_sales_returns():
    require_permission("sales")
    st.title("🔄 Returns")
    inv = st.text_input("Invoice Number")
    if inv:
        with get_db_connection() as conn:
            sale = conn.execute("SELECT id, net_amount FROM sales WHERE invoice_number=?", (inv,)).fetchone()
            if not sale: st.error("Invoice not found"); return
            items = conn.execute("SELECT si.id, m.name, si.quantity, si.unit_price FROM sale_items si JOIN medicines m ON si.medicine_id=m.id WHERE si.sale_id=?", (sale[0],)).fetchall()
        for it in items:
            col1,col2,col3 = st.columns([3,1,1])
            col1.write(f"{it[1]} - Sold: {it[2]}")
            ret_qty = col2.number_input("Return Qty",0,it[2], key=f"ret_{it[0]}")
            if col3.button("Return", key=f"retbtn_{it[0]}"):
                if ret_qty>0:
                    refund = ret_qty * it[3]
                    with get_db_connection() as conn2:
                        conn2.execute("UPDATE medicines SET current_stock = current_stock + ? WHERE id = (SELECT medicine_id FROM sale_items WHERE id=?)", (ret_qty, it[0]))
                        conn2.execute("INSERT INTO sales_returns (original_sale_id, sale_item_id, quantity_returned, refund_amount, reason, created_by) VALUES (?,?,?,?,'Customer return',?)", (sale[0], it[0], ret_qty, refund, st.session_state.user['id']))
                        conn2.commit()
                    st.success(f"Returned {ret_qty} units, refund ${refund:.2f}"); st.rerun()

def render_label_printing():
    require_permission("label_print")
    st.title("🏷️ Labels")
    with get_db_connection() as conn:
        meds = conn.execute("SELECT id,name,generic_name,unit_price FROM medicines").fetchall()
    if not meds: st.warning("No medicines")
    else:
        med_opts = {m[0]: f"{m[1]} ({m[2]})" for m in meds}
        med_id = st.selectbox("Medicine", list(med_opts.keys()), format_func=lambda x:med_opts[x])
        med = next(m for m in meds if m[0]==med_id)
        s = get_settings_dict()
        dosage = st.text_input("Dosage Instructions", "Take as directed")
        if st.button("Generate Label"):
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial","B",16); pdf.cell(200,10,s.get("pharmacy_name","Pharmacy"), ln=1, align='C')
            pdf.set_font("Arial","",12)
            pdf.cell(200,10,f"Medicine: {med[1]}", ln=1)
            pdf.cell(200,10,f"Generic: {med[2]}", ln=1)
            pdf.cell(200,10,f"Price: ${med[3]:.2f}", ln=1)
            pdf.cell(200,10,f"Dosage: {dosage}", ln=1)
            pdf.cell(200,10,f"Pharmacist: {st.session_state.user['full_name']}", ln=1)
            qr = generate_qr(f"Med: {med[1]}\nDosage: {dosage}")
            qr_path = tempfile.mktemp(".png")
            qr.save(qr_path)
            pdf.image(qr_path, x=150, y=80, w=40)
            os.unlink(qr_path)
            st.download_button("Download Label", data=pdf.output(dest='S').encode('latin1'), file_name=f"label_{med[1]}.pdf", mime="application/pdf")

def render_suppliers():
    require_permission("suppliers")
    st.title("🚚 Suppliers")
    with get_db_connection() as conn:
        sups = conn.execute("SELECT * FROM suppliers").fetchall()
    for s in sups:
        with st.expander(f"{s['name']} - {s.get('contact_person','')}"):
            st.write(f"📞 {s['phone']} | 📧 {s['email']} | GST: {s['gst_number']}")
    with st.form("add_supplier"):
        name = st.text_input("Name")
        contact = st.text_input("Contact Person")
        phone = st.text_input("Phone")
        email = st.text_input("Email")
        addr = st.text_area("Address")
        gst = st.text_input("GST")
        terms = st.text_input("Payment Terms")
        if st.form_submit_button("Add"):
            with get_db_connection() as conn:
                conn.execute("INSERT INTO suppliers (name,contact_person,phone,email,address,gst_number,payment_terms) VALUES (?,?,?,?,?,?,?)", (name,contact,phone,email,addr,gst,terms))
                conn.commit()
            st.rerun()

def render_reports():
    require_permission("reports")
    st.title("📊 Reports")
    rep = st.selectbox("Type", ["Daily Sales","Monthly Sales","Inventory Report","Expiry Report"])
    if rep=="Daily Sales":
        d = st.date_input("Date", datetime.now().date())
        with get_db_connection() as conn:
            rows = conn.execute("SELECT invoice_number, net_amount, payment_method, created_at, u.full_name FROM sales s JOIN users u ON s.user_id=u.id WHERE DATE(s.created_at)=? ORDER BY s.created_at", (d.isoformat(),)).fetchall()
        df = pd.DataFrame([dict(r) for r in rows])
        st.dataframe(df)
        if not df.empty:
            st.metric("Total", f"${df['net_amount'].sum():.2f}")
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='openpyxl') as writer: df.to_excel(writer, index=False)
            st.download_button("Export Excel", data=buf.getvalue(), file_name=f"sales_{d}.xlsx")
    elif rep=="Monthly Sales":
        month = st.selectbox("Month", range(1,13), format_func=lambda x: datetime(2000,x,1).strftime("%B"))
        year = st.number_input("Year", 2020, value=datetime.now().year)
        with get_db_connection() as conn:
            rows = conn.execute("SELECT strftime('%Y-%m-%d', created_at) as day, SUM(net_amount) as sales FROM sales WHERE strftime('%Y', created_at)=? AND strftime('%m', created_at)=? GROUP BY day ORDER BY day", (str(year), f"{month:02d}")).fetchall()
        if rows:
            df = pd.DataFrame([{"date":r[0],"sales":r[1]} for r in rows])
            fig = px.line(df, x='date', y='sales', title=f"{datetime(year,month,1).strftime('%B %Y')} Sales")
            st.plotly_chart(fig)
    elif rep=="Inventory Report":
        with get_db_connection() as conn:
            rows = conn.execute("SELECT name, current_stock, reorder_level, unit_price FROM medicines").fetchall()
        df = pd.DataFrame([dict(r) for r in rows])
        st.dataframe(df)
        fig = px.bar(df, x='name', y='current_stock', title='Current Stock')
        st.plotly_chart(fig)
    elif rep=="Expiry Report":
        df = get_expiring(90)
        st.dataframe(df)
        if not df.empty: fig = px.bar(df, x='name', y='qty', color='expiry', title='Expiring Batches'); st.plotly_chart(fig)

def render_staff_management():
    require_permission("staff")
    st.title("👨‍💼 Staff")
    tab1,tab2,tab3 = st.tabs(["Employees","Roles","Attendance"])
    with tab1:
        with get_db_connection() as conn:
            users = conn.execute("SELECT u.*, r.name as role_name FROM users u JOIN roles r ON u.role_id=r.id").fetchall()
        for u in users: st.write(f"{u['full_name']} ({u['username']}) - {u['role_name']}")
        with st.form("add_emp"):
            uname = st.text_input("Username")
            pwd = st.text_input("Password", type="password")
            full = st.text_input("Full Name")
            email = st.text_input("Email")
            with get_db_connection() as conn:
                roles = conn.execute("SELECT id,name FROM roles").fetchall()
            role_opt = {r[0]:r[1] for r in roles}
            role = st.selectbox("Role", list(role_opt.keys()), format_func=lambda x:role_opt[x])
            if st.form_submit_button("Add"):
                with get_db_connection() as conn:
                    conn.execute("INSERT INTO users (username,password_hash,full_name,email,role_id,must_change_password) VALUES (?,?,?,?,?,1)", (uname, generate_password_hash(pwd), full, email, role))
                    conn.commit()
                st.rerun()
    with tab2:
        with get_db_connection() as conn:
            for r in conn.execute("SELECT * FROM roles").fetchall():
                st.write(f"**{r['name']}**")
                st.json(json.loads(r['permissions']))
    with tab3:
        today = date.today()
        with get_db_connection() as conn:
            staff = conn.execute("SELECT id, full_name FROM users WHERE is_active=1").fetchall()
        for emp in staff:
            col1,col2,col3 = st.columns([2,1,1])
            col1.write(emp[1])
            ci = col2.time_input("Check In", datetime.now().time(), key=f"in_{emp[0]}")
            co = col3.time_input("Check Out", datetime.now().time(), key=f"out_{emp[0]}")
            if st.button(f"Mark", key=f"att_{emp[0]}"):
                with get_db_connection() as conn:
                    conn.execute("INSERT OR REPLACE INTO staff_attendance (user_id,date,check_in,check_out,status) VALUES (?,?,?,?,'present')", (emp[0], today, ci.strftime("%H:%M"), co.strftime("%H:%M")))
                    conn.commit()
                st.success(f"Marked for {emp[1]}")

def render_notifications():
    require_permission("all")
    st.title("🔔 Notifications")
    with get_db_connection() as conn:
        notifs = conn.execute("SELECT * FROM notifications ORDER BY created_at DESC").fetchall()
    for n in notifs:
        if n['type']=='warning': st.warning(f"**{n['title']}**: {n['message']}")
        elif n['type']=='danger': st.error(f"**{n['title']}**: {n['message']}")
        else: st.info(f"**{n['title']}**: {n['message']}")
    if st.button("Clear All"):
        with get_db_connection() as conn: conn.execute("DELETE FROM notifications"); conn.commit()
        st.rerun()

def render_audit_logs():
    require_permission("audit")
    st.title("📜 Audit Logs")
    with get_db_connection() as conn:
        logs = conn.execute("SELECT al.*, u.full_name FROM audit_logs al LEFT JOIN users u ON al.user_id=u.id ORDER BY al.created_at DESC LIMIT 100").fetchall()
    df = pd.DataFrame([dict(r) for r in logs])
    st.dataframe(df[['created_at','full_name','action','details']])

def render_advanced_features():
    require_permission("advanced")
    st.title("🚀 Advanced")
    tab1,tab2,tab3,tab4 = st.tabs(["Drug Interactions","Stock Forecasting","Loyalty","Appointments"])
    with tab1:
        with get_db_connection() as conn:
            meds = conn.execute("SELECT id,name FROM medicines").fetchall()
        opts = {m[0]:m[1] for m in meds}
        if opts:
            m1 = st.selectbox("Medicine 1", list(opts.keys()), format_func=lambda x:opts[x])
            m2 = st.selectbox("Medicine 2", list(opts.keys()), format_func=lambda x:opts[x])
            if st.button("Check Interaction"):
                with get_db_connection() as conn:
                    inter = conn.execute("SELECT severity, description FROM drug_interactions WHERE (medicine1_id=? AND medicine2_id=?) OR (medicine1_id=? AND medicine2_id=?)", (m1,m2,m2,m1)).fetchone()
                if inter: st.warning(f"Interaction: {inter[0]} - {inter[1]}")
                else: st.success("No known interaction")
            st.subheader("Add New Interaction")
            sev = st.selectbox("Severity", ["Mild","Moderate","Severe"])
            desc = st.text_area("Description")
            if st.button("Add Interaction"):
                with get_db_connection() as conn:
                    conn.execute("INSERT INTO drug_interactions (medicine1_id,medicine2_id,severity,description) VALUES (?,?,?,?)", (m1,m2,sev,desc))
                    conn.commit()
                st.success("Interaction added")
        else:
            st.info("Add medicines first to define interactions.")
    with tab2:
        with get_db_connection() as conn:
            meds = conn.execute("SELECT id,name FROM medicines").fetchall()
        if meds:
            med_for = st.selectbox("Select Medicine", [m[1] for m in meds])
            if med_for:
                med_id = next(m[0] for m in meds if m[1]==med_for)
                forecast = stock_forecast(med_id, 30)
                if forecast: st.info(f"Forecast for next 30 days: {forecast} units")
                else: st.warning("Insufficient data for forecast")
        else: st.info("No medicines")
    with tab3:
        with get_db_connection() as conn:
            loyal = conn.execute("SELECT p.first_name, p.last_name, lp.points FROM loyalty_points lp JOIN patients p ON lp.patient_id=p.id ORDER BY lp.points DESC").fetchall()
        if loyal:
            df = pd.DataFrame([{"name":f"{r[0]} {r[1]}","points":r[2]} for r in loyal])
            st.dataframe(df)
            st.metric("Total Points", df['points'].sum())
        else: st.info("No loyalty data")
    with tab4:
        with get_db_connection() as conn:
            patients = conn.execute("SELECT id, patient_id, first_name, last_name FROM patients").fetchall()
        pat_opts = {p[0]: f"{p[2]} {p[3]} ({p[1]})" for p in patients}
        if pat_opts:
            pid = st.selectbox("Patient", list(pat_opts.keys()), format_func=lambda x:pat_opts[x])
            app_date = st.date_input("Date", datetime.now().date())
            app_time = st.time_input("Time")
            purpose = st.text_input("Purpose")
            if st.button("Book"):
                with get_db_connection() as conn:
                    conn.execute("INSERT INTO appointments (patient_id,appointment_date,appointment_time,purpose) VALUES (?,?,?,?)", (pid, app_date, app_time.strftime("%H:%M"), purpose))
                    conn.commit()
                st.success("Appointment booked"); st.rerun()
        else: st.info("No patients registered")

def render_ai_assistant():
    require_permission("all")
    st.title("🤖 AI Assistant")
    st.markdown("Ask about symptoms, stock, expiries, interactions.")
    if "ai_msgs" not in st.session_state: st.session_state.ai_msgs = [{"role":"assistant","content":"Hello! I'm your pharmacy AI assistant. How can I help?"}]
    for m in st.session_state.ai_msgs:
        if m["role"]=="user": st.chat_message("user").write(m["content"])
        else: st.chat_message("assistant").write(m["content"])
    inp = st.chat_input("Ask me anything...")
    if inp:
        st.session_state.ai_msgs.append({"role":"user","content":inp})
        st.chat_message("user").write(inp)
        resp = ai_response(inp)
        st.session_state.ai_msgs.append({"role":"assistant","content":resp})
        st.chat_message("assistant").write(resp)
        log_audit(st.session_state.user['id'], "AI_QUERY", inp[:100])

def render_settings():
    require_permission("all")
    if st.session_state.user['role_name']!="Admin": st.error("Admin only"); return
    st.title("⚙️ Settings")
    s = get_settings_dict()
    st.subheader("General")
    ph_name = st.text_input("Pharmacy Name", s.get("pharmacy_name",""))
    ph_addr = st.text_area("Address", s.get("pharmacy_address",""))
    ph_phone = st.text_input("Phone", s.get("pharmacy_phone",""))
    ph_email = st.text_input("Email", s.get("pharmacy_email",""))
    tax_num = st.text_input("Tax Number", s.get("tax_number",""))
    lic = st.text_input("License Number", s.get("pharmacist_license",""))
    footer = st.text_area("Receipt Footer", s.get("receipt_footer",""))
    gst = st.number_input("GST Rate (%)", 0.0, 100.0, value=float(s.get("gst_rate",5)))
    if st.button("Save Settings"):
        update_setting("pharmacy_name", ph_name); update_setting("pharmacy_address", ph_addr)
        update_setting("pharmacy_phone", ph_phone); update_setting("pharmacy_email", ph_email)
        update_setting("tax_number", tax_num); update_setting("pharmacist_license", lic)
        update_setting("receipt_footer", footer); update_setting("gst_rate", str(gst))
        st.success("Settings saved"); st.rerun()
    st.subheader("Backup")
    if st.button("Create Backup"):
        backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy(DB_PATH, backup_name)
        with open(backup_name, "rb") as f: st.download_button("Download Backup", data=f, file_name=backup_name)

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
    st.set_page_config(page_title="Pharmacy Management System", layout="wide", page_icon="💊")
    st.sidebar.image("https://img.icons8.com/fluency/96/pill.png", width=80)
    st.sidebar.title(f"Welcome, {st.session_state.user['full_name']}")
    st.sidebar.write(f"Role: {st.session_state.user['role_name']}")
    menu = ["Dashboard","Medicines","Inventory","Patients","Prescriptions","Sales & Billing","Sales Returns","Label Printing","Suppliers","Reports","Staff Management","Notifications","Audit Logs","Advanced Features","AI Assistant","Settings"]
    user_perms = json.loads(st.session_state.user.get('permissions','{}'))
    allowed = []
    for m in menu:
        if m in ["Dashboard","Notifications","AI Assistant","Settings"]: allowed.append(m)
        elif m=="Medicines" and (user_perms.get('all') or user_perms.get('medicines')): allowed.append(m)
        elif m=="Inventory" and (user_perms.get('all') or user_perms.get('inventory')): allowed.append(m)
        elif m in ["Patients","Prescriptions"] and (user_perms.get('all') or user_perms.get('patients_view') or user_perms.get('prescriptions')): allowed.append(m)
        elif m in ["Sales & Billing","Sales Returns"] and (user_perms.get('all') or user_perms.get('sales')): allowed.append(m)
        elif m=="Label Printing" and (user_perms.get('all') or user_perms.get('label_print')): allowed.append(m)
        elif m=="Suppliers" and (user_perms.get('all') or user_perms.get('suppliers')): allowed.append(m)
        elif m=="Reports" and (user_perms.get('all') or user_perms.get('reports')): allowed.append(m)
        elif m=="Staff Management" and (user_perms.get('all') or user_perms.get('staff')): allowed.append(m)
        elif m=="Audit Logs" and (user_perms.get('all') or user_perms.get('audit')): allowed.append(m)
        elif m=="Advanced Features" and (user_perms.get('all') or user_perms.get('advanced')): allowed.append(m)
    for m in allowed:
        if st.sidebar.button(m, use_container_width=True): st.session_state.page = m
    if st.sidebar.button("🚪 Logout", use_container_width=True): logout_user()
    page = st.session_state.get('page', 'Dashboard')
    if page=="Dashboard": render_dashboard()
    elif page=="Medicines": render_medicines()
    elif page=="Inventory": render_inventory()
    elif page=="Patients": render_patients()
    elif page=="Prescriptions": render_prescriptions()
    elif page=="Sales & Billing": render_sales_billing()
    elif page=="Sales Returns": render_sales_returns()
    elif page=="Label Printing": render_label_printing()
    elif page=="Suppliers": render_suppliers()
    elif page=="Reports": render_reports()
    elif page=="Staff Management": render_staff_management()
    elif page=="Notifications": render_notifications()
    elif page=="Audit Logs": render_audit_logs()
    elif page=="Advanced Features": render_advanced_features()
    elif page=="AI Assistant": render_ai_assistant()
    elif page=="Settings": render_settings()
    else: render_dashboard()

if __name__ == "__main__":
    main()
