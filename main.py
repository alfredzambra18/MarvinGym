import os
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'marvin_gym_secret_key_2026'

UPLOAD_FOLDER = os.path.join('static', 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

PAGO_MOVIL = {
    "banco": "Banesco (0134)",
    "cedula": "V-13210442",
    "telefono": "0412-3931166"
}

def init_db():
    conn = sqlite3.connect('gym.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            cedula TEXT NOT NULL UNIQUE,
            telefono TEXT NOT NULL,
            password TEXT NOT NULL,
            fecha_vencimiento DATE DEFAULT '2000-01-01'
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS pagos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            tipo_plan TEXT NOT NULL,
            monto REAL NOT NULL,
            referencia TEXT NOT NULL,
            comprobante_path TEXT NOT NULL,
            estado TEXT DEFAULT 'Pendiente',
            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS caja (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            monto REAL NOT NULL,
            concepto TEXT NOT NULL,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    if 'usuario_id' in session:
        return redirect(url_for('perfil'))
    return redirect(url_for('login'))

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre = request.form['nombre']
        cedula = request.form['cedula'].strip()
        telefono = request.form['telefono'].strip()
        password = request.form['password']

        hashed_pw = generate_password_hash(password)

        conn = sqlite3.connect('gym.db')
        c = conn.cursor()
        try:
            c.execute('INSERT INTO usuarios (nombre, cedula, telefono, password) VALUES (?, ?, ?, ?)',
                      (nombre, cedula, telefono, hashed_pw))
            conn.commit()
            flash('¡Cuenta creada con éxito! Inicia sesión.')
            conn.close()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            conn.close()
            flash('Error: La cédula ya se encuentra registrada.')

    return render_template('registro.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        cedula = request.form['cedula'].strip()
        password = request.form['password']

        conn = sqlite3.connect('gym.db')
        c = conn.cursor()
        c.execute('SELECT id, nombre, password FROM usuarios WHERE cedula = ?', (cedula,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[2], password):
            session['usuario_id'] = user[0]
            session['usuario_nombre'] = user[1]
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
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect('gym.db')
    c = conn.cursor()

    c.execute('SELECT nombre, cedula, telefono, fecha_vencimiento FROM usuarios WHERE id = ?', (session['usuario_id'],))
    user = c.fetchone()

    c.execute('SELECT tipo_plan, monto, referencia, estado, fecha_registro FROM pagos WHERE usuario_id = ? ORDER BY fecha_registro DESC', (session['usuario_id'],))
    facturas = c.fetchall()
    conn.close()

    hoy = datetime.now().date()
    vencimiento = datetime.strptime(user[3], '%Y-%m-%d').date()
    dias_restantes = (vencimiento - hoy).days
    
    estado_membresia = "ACTIVA" if dias_restantes > 0 else "VENCIDA"

    return render_template('perfil.html', user={
        'nombre': user[0],
        'cedula': user[1],
        'telefono': user[2],
        'vencimiento': user[3],
        'dias': dias_restantes,
        'estado': estado_membresia
    }, facturas=facturas, pago_movil=PAGO_MOVIL)

@app.route('/reportar_pago', methods=['POST'])
def reportar_pago():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    tipo_plan = request.form['tipo_plan']
    referencia = request.form['referencia']
    file = request.files['comprobante']

    monto = 10.0 if tipo_plan == 'Mensualidad' else 1.0

    if file:
        filename = secure_filename(f"{session['usuario_id']}_{referencia}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        conn = sqlite3.connect('gym.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO pagos (usuario_id, tipo_plan, monto, referencia, comprobante_path)
            VALUES (?, ?, ?, ?, ?)
        ''', (session['usuario_id'], tipo_plan, monto, referencia, filename))
        conn.commit()
        conn.close()
        flash('Pago reportado con éxito. Está en proceso de verificación.')

    return redirect(url_for('perfil'))

@app.route('/admin')
def admin():
    conn = sqlite3.connect('gym.db')
    c = conn.cursor()

    c.execute('''
        SELECT p.id, u.nombre, u.cedula, p.tipo_plan, p.monto, p.referencia, p.comprobante_path 
        FROM pagos p 
        JOIN usuarios u ON p.usuario_id = u.id 
        WHERE p.estado = 'Pendiente' 
        ORDER BY p.fecha_registro DESC
    ''')
    pendientes = c.fetchall()

    c.execute('SELECT id, nombre, cedula, telefono, fecha_vencimiento FROM usuarios ORDER BY fecha_vencimiento ASC')
    socios = c.fetchall()
    
    hoy = datetime.now().date()
    socios_list = []
    for s in socios:
        venc = datetime.strptime(s[4], '%Y-%m-%d').date()
        dias = (venc - hoy).days
        alerta = 'green' if dias > 3 else ('yellow' if dias >= 0 else 'red')
        socios_list.append({
            'id': s[0], 'nombre': s[1], 'cedula': s[2], 'telefono': s[3],
            'fecha_vencimiento': s[4], 'dias': dias, 'alerta': alerta
        })

    c.execute('SELECT SUM(monto) FROM caja')
    balance = c.fetchone()[0] or 0.0

    conn.close()
    return render_template('admin.html', pendientes=pendientes, socios=socios_list, balance=balance)

@app.route('/aprobar_pago/<int:pago_id>')
def aprobar_pago(pago_id):
    conn = sqlite3.connect('gym.db')
    c = conn.cursor()

    c.execute('SELECT usuario_id, tipo_plan, monto, referencia FROM pagos WHERE id = ?', (pago_id,))
    pago = c.fetchone()

    if pago:
        usuario_id, tipo_plan, monto, referencia = pago
        dias_plan = 30 if tipo_plan == 'Mensualidad' else 1

        c.execute('SELECT fecha_vencimiento, nombre FROM usuarios WHERE id = ?', (usuario_id,))
        user = c.fetchone()

        hoy = datetime.now().date()
        venc_actual = datetime.strptime(user[0], '%Y-%m-%d').date()
        base_fecha = max(hoy, venc_actual)
        nueva_fecha = base_fecha + timedelta(days=dias_plan)

        c.execute('UPDATE usuarios SET fecha_vencimiento = ? WHERE id = ?', (nueva_fecha.strftime('%Y-%m-%d'), usuario_id))
        c.execute("UPDATE pagos SET estado = 'Aprobado' WHERE id = ?", (pago_id,))
        c.execute('INSERT INTO caja (monto, concepto) VALUES (?, ?)', (monto, f"Pago {tipo_plan} - Ref: {referencia} ({user[1]})"))
        
        conn.commit()

    conn.close()
    return redirect(url_for('admin'))

@app.route('/eliminar_pago/<int:pago_id>')
def eliminar_pago(pago_id):
    conn = sqlite3.connect('gym.db')
    c = conn.cursor()
    c.execute("UPDATE pagos SET estado = 'Rechazado' WHERE id = ?", (pago_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
