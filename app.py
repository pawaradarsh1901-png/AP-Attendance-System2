from flask import Flask, request, jsonify, render_template, send_file, session, redirect, url_for
import functools
import sqlite3
import datetime
import uuid
import os
import qrcode
from io import BytesIO

app = Flask(__name__)
app.secret_key = 'secure_attendance_key_123'  # Needed for session management
DATABASE = 'attendance.db'

# Hardcoded Admin Credentials
ADMIN_USER = 'admin'
ADMIN_PASS = 'admin'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            emp_id TEXT NOT NULL UNIQUE,
            qr_token TEXT NOT NULL UNIQUE,
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            in_time TEXT,
            out_time TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    conn.commit()
    conn.close()

def migrate_db():
    conn = get_db()
    try:
        conn.execute('ALTER TABLE users ADD COLUMN phone TEXT')
        conn.commit()
        print("Migration: Added phone column to users table")
    except sqlite3.OperationalError:
        # Column already exists
        pass
    conn.close()

# Initialize the db on startup
init_db()
migrate_db()

# --- Authentication Middleware ---
def login_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            # If it's an API route, send JSON 401
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Unauthorized'}), 401
            # Otherwise redirect to login
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

# --- Frontend Routes ---
@app.route('/')
def scanner_panel():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        data = request.json
        if not data:
            data = request.form
        username = data.get('username')
        password = data.get('password')

        if username == ADMIN_USER and password == ADMIN_PASS:
            session['logged_in'] = True
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Invalid credentials'}), 401

    if 'logged_in' in session:
        return redirect(url_for('admin_panel'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login_page'))

@app.route('/admin')
@login_required
def admin_panel():
    return render_template('admin.html')

# --- API Endpoints ---
@app.route('/api/users', methods=['GET'])
@login_required
def get_users():
    conn = get_db()
    users = conn.execute('SELECT * FROM users ORDER BY created_at DESC').fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])

@app.route('/api/users', methods=['POST'])
@login_required
def create_user():
    data = request.json
    name = data.get('name')
    emp_id = data.get('emp_id')
    phone = data.get('phone')
    if not name or not emp_id:
        return jsonify({'error': 'Name and Student ID required'}), 400
    
    qr_token = str(uuid.uuid4())
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (name, emp_id, qr_token, phone) VALUES (?, ?, ?, ?)", (name, emp_id, qr_token, phone))
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()
        return jsonify({'id': new_id, 'name': name, 'emp_id': emp_id, 'qr_token': qr_token}), 201
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Roll No / Student ID already exists'}), 400

@app.route('/api/qr/<qr_token>')
def generate_qr(qr_token):
    img = qrcode.make(qr_token)
    buf = BytesIO()
    img.save(buf)
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

@app.route('/api/scan', methods=['POST'])
def scan_qr():
    # Public endpoint allowing the kiosk scanner to submit data
    data = request.json
    qr_token = data.get('qr_token')
    if not qr_token:
        return jsonify({'error': 'QR Token required'}), 400

    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE qr_token = ?', (qr_token,)).fetchone()
    
    if not user:
        conn.close()
        return jsonify({'error': 'Invalid QR Code / User Not Found'}), 404

    user_id = user['id']
    display_name = user['name']
    today = datetime.date.today().isoformat()
    now_time = datetime.datetime.now().strftime("%H:%M:%S")

    # Check if there is an attendance record for today
    att = conn.execute('SELECT * FROM attendance WHERE user_id = ? AND date = ?', (user_id, today)).fetchone()

    status = ""
    if not att:
        # First scan of the day -> In Time
        conn.execute('INSERT INTO attendance (user_id, date, in_time) VALUES (?, ?, ?)', (user_id, today, now_time))
        status = "IN"
    else:
        # Subsequent scan -> Out Time (updates to the latest scan)
        conn.execute('UPDATE attendance SET out_time = ? WHERE id = ?', (now_time, att['id']))
        status = "OUT"

    conn.commit()
    conn.close()

    # Send message notification (Implementation placeholder)
    if user['phone']:
        send_attendance_msg(user['phone'], display_name, status, now_time)

    return jsonify({
        'message': f'Attendance marked {status} successfully',
        'status': status,
        'user': display_name,
        'time': now_time
    })

def send_attendance_msg(phone, name, status, time):
    """
    Placeholder for sending SMS/WhatsApp message.
    In a real app, you would use Twilio, Vonage, or a WhatsApp Business API here.
    """
    msg = f"Hello {name}, you have been marked {status} in the lab at {time}."
    print(f"DEBUG: Sending message to {phone}: {msg}")
    # Integration example (requires library like 'twilio'):
    # client = Client(account_sid, auth_token)
    # client.messages.create(body=msg, from_=twilio_num, to=phone)

@app.route('/api/attendance', methods=['GET'])
@login_required
def get_attendance():
    date_filter = request.args.get('date', 'today')
    conn = get_db()
    
    if date_filter == 'all':
        query = '''
            SELECT a.id, u.name, u.emp_id, a.date, a.in_time, a.out_time
            FROM attendance a
            JOIN users u ON a.user_id = u.id
            ORDER BY a.date DESC, a.in_time DESC
        '''
        logs = conn.execute(query).fetchall()
    else:
        actual_date = datetime.date.today().isoformat() if date_filter == 'today' else date_filter
        query = '''
            SELECT a.id, u.name, u.emp_id, a.date, a.in_time, a.out_time
            FROM attendance a
            JOIN users u ON a.user_id = u.id
            WHERE a.date = ?
            ORDER BY a.in_time DESC
        '''
        logs = conn.execute(query, (actual_date,)).fetchall()
        
    conn.close()
    return jsonify([dict(l) for l in logs])

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
