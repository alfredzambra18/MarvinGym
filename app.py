import os
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for
from werkzeug.utils import secure_filename

app = Flask(__name__)

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DATOS_PAGO_MOVIL = {
    "banco": "Banco Nacional de Crédito (BNC)",
    "cedula": "13.210.442",
    "telefono": "04123931166"
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    conn = sqlite3.connect('marvin_gym.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS miembros (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                cedula TEXT UNIQUE NOT NULL,
                telefono TEXT NOT NULL,
                fecha_vencimiento DATE NOT NULL,
                estado TEXT DEFAULT 'Activo'
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS pagos_pendientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                cedula TEXT NOT NULL,
                telefono TEXT NOT NULL,
                tipo_plan TEXT NOT NULL,
                monto REAL NOT NULL,
                referencia TEXT NOT NULL,
                comprobante_path TEXT NOT NULL,
                fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
                estado TEXT DEFAULT 'Pendiente'
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS contabilidad (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo TEXT NOT NULL,
                monto REAL NOT NULL,
                descripcion TEXT NOT NULL,
                fecha DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()

init_db()

@app.route('/')
def index():
    enviado = request.args.get('enviado')
    return render_template('index.html', pago_movil=DATOS_PAGO_MOVIL, enviado=enviado)

@app.route('/reportar_pago', methods=['POST'])
def reportar_pago():
    nombre = request.form['nombre']
    cedula = request.form['cedula']
    telefono = request.form['telefono']
    tipo_plan = request.form['tipo_plan']
    referencia = request.form['referencia']
    file = request.files['comprobante']

    monto = 10.00 if tipo_plan == 'Mensualidad' else 1.00

    if file and allowed_file(file.filename):
        filename = secure_filename(f"{cedula}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        with get_db() as conn:
            conn.execute('''
                INSERT INTO pagos_pendientes (nombre, cedula, telefono, tipo_plan, monto, referencia, comprobante_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (nombre, cedula, telefono, tipo_plan, monto, referencia, filename))
            conn.commit()

        return redirect(url_for('index', enviado=1))

    return "Error al subir comprobante", 400

@app.route('/admin')
def admin():
    hoy = datetime.now().date()
    with get_db() as conn:
        miembros = conn.execute('SELECT * FROM miembros').fetchall()
        pendientes = conn.execute('SELECT * FROM pagos_pendientes WHERE estado = "Pendiente"').fetchall()
        
        ingresos = conn.execute("SELECT SUM(monto) as total FROM contabilidad WHERE tipo = 'Ingreso'").fetchone()['total'] or 0
        gastos = conn.execute("SELECT SUM(monto) as total FROM contabilidad WHERE tipo = 'Gasto'").fetchone()['total'] or 0

    miembros_procesados = []
    for m in miembros:
        venc = datetime.strptime(m['fecha_vencimiento'], '%Y-%m-%d').date()
        dias = (venc - hoy).days
        alerta = 'red' if dias < 0 else ('yellow' if dias <= 3 else 'green')
        miembros_procesados.append({**dict(m), 'dias': dias, 'alerta': alerta})

    return render_template('admin.html', miembros=miembros_procesados, pendientes=pendientes, balance=ingresos - gastos)

@app.route('/aprobar_pago/<int:id>')
def aprobar_pago(id):
    hoy = datetime.now().date()
    with get_db() as conn:
        pago = conn.execute('SELECT * FROM pagos_pendientes WHERE id = ?', (id,)).fetchone()
        if pago:
            miembro = conn.execute('SELECT * FROM miembros WHERE cedula = ?', (pago['cedula'],)).fetchone()
            
            dias_sumar = 30 if pago['tipo_plan'] == 'Mensualidad' else 1
            
            if miembro:
                venc_actual = datetime.strptime(miembro['fecha_vencimiento'], '%Y-%m-%d').date()
                nueva_fecha = max(venc_actual, hoy) + timedelta(days=dias_sumar)
                conn.execute('UPDATE miembros SET fecha_vencimiento = ? WHERE id = ?', (nueva_fecha.strftime('%Y-%m-%d'), miembro['id']))
            else:
                nueva_fecha = hoy + timedelta(days=dias_sumar)
                conn.execute('''
                    INSERT INTO miembros (nombre, cedula, telefono, fecha_vencimiento)
                    VALUES (?, ?, ?, ?)
                ''', (pago['nombre'], pago['cedula'], pago['telefono'], nueva_fecha.strftime('%Y-%m-%d')))

            conn.execute('UPDATE pagos_pendientes SET estado = "Aprobado" WHERE id = ?', (id,))
            conn.execute('INSERT INTO contabilidad (tipo, monto, descripcion) VALUES ("Ingreso", ?, ?)',
                         (pago['monto'], f"Pago {pago['tipo_plan']} - {pago['nombre']}"))
            conn.commit()

    return redirect(url_for('admin'))

@app.route('/eliminar_miembro/<int:id>')
def eliminar_miembro(id):
    with get_db() as conn:
        conn.execute('DELETE FROM miembros WHERE id = ?', (id,))
        conn.commit()
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(debug=True)
