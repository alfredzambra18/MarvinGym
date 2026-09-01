import os
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'marvingym_key_2026'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

PAGO_MOVIL = {
    "banco": "Banesco (0134)",
    "cedula": "V-13210442",
    "telefono": "04141234567"
}

def get_db_connection():
    conn = sqlite3.connect('gym.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS socios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cedula TEXT UNIQUE NOT NULL,
            nombre TEXT NOT NULL,
            telefono TEXT NOT NULL,
            password TEXT NOT NULL,
            vencimiento DATE,
            monto_ultimo_pago REAL DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pagos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            socio_id INTEGER,
            tipo_plan TEXT NOT NULL,
            monto REAL NOT NULL,
            referencia TEXT NOT NULL,
            comprobante TEXT NOT NULL,
            estado TEXT DEFAULT 'Pendiente',
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (socio_id) REFERENCES socios (id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contabilidad (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            monto REAL NOT NULL,
            descripcion TEXT NOT NULL,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def home():
    if 'socio_id' in session:
        return redirect(url_for('perfil'))
    return redirect(url_for('login'))

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        cedula = request.form.get('cedula', '').strip()
        telefono = request.form.get('telefono', '').strip()
        password = request.form.get('password', '').strip()
        
        if not nombre or not cedula or not password:
            flash('Por favor completa todos los campos requeridos.')
            return redirect(url_for('registro'))

        hashed_pw = generate_password_hash(password)
        
        conn = get_db_connection()
        try:
            conn.execute(
                'INSERT INTO socios (nombre, cedula, telefono, password) VALUES (?, ?, ?, ?)',
                (nombre, cedula, telefono, hashed_pw)
            )
            conn.commit()
            flash('¡Registro exitoso! Por favor inicia sesión.')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('La cédula ya se encuentra registrada.')
        finally:
            conn.close()
            
    return render_template('registro.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        cedula = request.form.get('cedula', '').strip()
        password = request.form.get('password', '').strip()
        
        conn = get_db_connection()
        socio = conn.execute('SELECT * FROM socios WHERE cedula = ?', (cedula,)).fetchone()
        conn.close()
        
        if socio and check_password_hash(socio['password'], password):
            session['socio_id'] = socio['id']
            session['socio_nombre'] = socio['nombre']
            return redirect(url_for('perfil'))
        else:
            flash('Cédula o contraseña incorrectas.')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/perfil')
def perfil():
    if 'socio_id' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    socio = conn.execute('SELECT * FROM socios WHERE id = ?', (session['socio_id'],)).fetchone()
    facturas = conn.execute(
        'SELECT tipo_plan, monto, referencia, estado, fecha FROM pagos WHERE socio_id = ? ORDER BY id DESC',
        (session['socio_id'],)
    ).fetchall()
    conn.close()
    
    if not socio:
        session.clear()
        return redirect(url_for('login'))

    estado = "VENCIDA"
    dias = 0
    venc_str = "No registrada"
    
    if socio['vencimiento']:
        try:
            venc_date = datetime.strptime(socio['vencimiento'], '%Y-%m-%d').date()
            today = datetime.now().date()
            dias = (venc_date - today).days
            venc_str = venc_date.strftime('%d/%m/%Y')
            if dias >= 0:
                estado = "ACTIVA"
        except ValueError:
            pass

    user_data = {
        'nombre': socio['nombre'],
        'cedula': socio['cedula'],
        'vencimiento': venc_str,
        'estado': estado,
        'dias': max(0, dias)
    }
    
    return render_template('perfil.html', user=user_data, pago_movil=PAGO_MOVIL, facturas=facturas)

@app.route('/reportar_pago', methods=['POST'])
def reportar_pago():
    if 'socio_id' not in session:
        return redirect(url_for('login'))
        
    tipo_plan = request.form.get('tipo_plan', 'Mensualidad')
    referencia = request.form.get('referencia', '').strip()
    file = request.files.get('comprobante')
    
    monto = 10.0 if tipo_plan == 'Mensualidad' else 1.0
    
    filename = ""
    if file and file.filename != '':
        filename = secure_filename(f"{session['socio_id']}_{int(datetime.now().timestamp())}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO pagos (socio_id, tipo_plan, monto, referencia, comprobante) VALUES (?, ?, ?, ?, ?)',
        (session['socio_id'], tipo_plan, monto, referencia, filename)
    )
    conn.commit()
    conn.close()
    
    flash('¡Comprobante enviado con éxito! El administrador lo verificará pronto.')
    return redirect(url_for('perfil'))

@app.route('/admin')
def admin():
    conn = get_db_connection()
    socios = conn.execute('SELECT * FROM socios ORDER BY id DESC').fetchall()
    pagos_pendientes = conn.execute('''
        SELECT p.id, s.nombre, s.cedula, p.tipo_plan, p.monto, p.referencia, p.comprobante, p.fecha
        FROM pagos p
        JOIN socios s ON p.socio_id = s.id
        WHERE p.estado = 'Pendiente'
        ORDER BY p.id DESC
    ''').fetchall()
    conn.close()
    
    return render_template('admin.html', socios=socios, pagos=pagos_pendientes)

@app.route('/admin/socio/<int:socio_id>')
def detalle_socio(socio_id):
    conn = get_db_connection()
    socio = conn.execute('SELECT * FROM socios WHERE id = ?', (socio_id,)).fetchone()
    facturas = conn.execute(
        'SELECT * FROM pagos WHERE socio_id = ? ORDER BY id DESC',
        (socio_id,)
    ).fetchall()
    conn.close()
    
    if not socio:
        flash('Socio no encontrado.')
        return redirect(url_for('admin'))
        
    return render_template('detalle_socio.html', socio=socio, facturas=facturas)

@app.route('/admin/aprobar_pago/<int:pago_id>')
def aprobar_pago(pago_id):
    conn = get_db_connection()
    pago = conn.execute('SELECT * FROM pagos WHERE id = ?', (pago_id,)).fetchone()
    
    if pago:
        conn.execute('UPDATE pagos SET estado = "Aprobado" WHERE id = ?', (pago_id,))
        
        hoy = datetime.now().date()
        socio = conn.execute('SELECT vencimiento FROM socios WHERE id = ?', (pago['socio_id'],)).fetchone()
        
        nueva_fecha = hoy + timedelta(days=30)
        if socio and socio['vencimiento']:
            try:
                venc_actual = datetime.strptime(socio['vencimiento'], '%Y-%m-%d').date()
                if venc_actual > hoy:
                    nueva_fecha = venc_actual + timedelta(days=30)
            except ValueError:
                pass
                
        conn.execute('UPDATE socios SET vencimiento = ?, monto_ultimo_pago = ? WHERE id = ?', 
                     (nueva_fecha.strftime('%Y-%m-%d'), pago['monto'], pago['socio_id']))
                     
        conn.execute('INSERT INTO contabilidad (tipo, monto, descripcion) VALUES ("Ingreso", ?, ?)',
                     (pago['monto'], f"Pago {pago['tipo_plan']} - Socio ID {pago['socio_id']}"))
                     
        conn.commit()
        
    conn.close()
    flash('Pago aprobado y membresía actualizada.')
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
