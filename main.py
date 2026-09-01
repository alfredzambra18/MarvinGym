import os
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'marvingym_clave_secreta_super_segura'

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

PAGO_MOVIL = {
    "banco": "Banco Nacional de Crédito (BNC)",
    "cedula": "13.210.442",
    "telefono": "04123931166"
}

def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS socios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            cedula TEXT UNIQUE NOT NULL,
            telefono TEXT NOT NULL,
            vencimiento TEXT DEFAULT 'Vencido'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS facturas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            socio_id INTEGER,
            tipo_plan TEXT,
            monto REAL,
            referencia TEXT,
            comprobante TEXT,
            estado TEXT DEFAULT 'Pendiente',
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (socio_id) REFERENCES socios (id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    if 'socio_id' in session:
        return redirect(url_for('perfil'))
    return redirect(url_for('login'))

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre = request.form['nombre'].strip()
        cedula = request.form['cedula'].strip()
        telefono = request.form['telefono'].strip()

        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT INTO socios (nombre, cedula, telefono) VALUES (?, ?, ?)',
                           (nombre, cedula, telefono))
            conn.commit()
            socio_id = cursor.lastrowid
            session['socio_id'] = socio_id
            session['socio_nombre'] = nombre
            conn.close()
            return redirect(url_for('perfil'))
        except sqlite3.IntegrityError:
            conn.close()
            flash('Esta cédula ya está registrada. Intenta iniciar sesión.')
            return redirect(url_for('login'))

    return render_template('registro.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        cedula = request.form['cedula'].strip()
        conn = get_db()
        cursor = conn.cursor()
        socio = cursor.execute('SELECT * FROM socios WHERE cedula = ?', (cedula,)).fetchone()
        conn.close()

        if socio:
            session['socio_id'] = socio['id']
            session['socio_nombre'] = socio['nombre']
            return redirect(url_for('perfil'))
        else:
            flash('Cédula no encontrada. Por favor regístrate primero.')
            return redirect(url_for('registro'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/perfil')
def perfil():
    if 'socio_id' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    cursor = conn.cursor()
    socio = cursor.execute('SELECT * FROM socios WHERE id = ?', (session['socio_id'],)).fetchone()
    facturas = cursor.execute('SELECT tipo_plan, monto, referencia, estado, fecha FROM facturas WHERE socio_id = ? ORDER BY id DESC', 
                              (session['socio_id'],)).fetchall()
    conn.close()

    venc_str = socio['vencimiento']
    dias_restantes = 0
    estado_membresia = "VENCIDA"

    if venc_str != 'Vencido':
        try:
            venc_dt = datetime.strptime(venc_str, '%Y-%m-%d')
            dias_restantes = (venc_dt - datetime.now()).days + 1
            if dias_restantes > 0:
                estado_membresia = "ACTIVA"
            else:
                dias_restantes = 0
        except ValueError:
            pass

    user_data = {
        "nombre": socio['nombre'],
        "cedula": socio['cedula'],
        "vencimiento": venc_str,
        "dias": dias_restantes,
        "estado": estado_membresia
    }

    return render_template('perfil.html', user=user_data, pago_movil=PAGO_MOVIL, facturas=facturas)

@app.route('/reportar_pago', methods=['POST'])
def reportar_pago():
    if 'socio_id' not in session:
        return redirect(url_for('login'))

    tipo_plan = request.form['tipo_plan']
    referencia = request.form['referencia'].strip()
    file = request.files.get('comprobante')

    monto = 10.0 if tipo_plan == "Mensualidad" else 1.0
    filename = ""

    if file and file.filename != '':
        filename = secure_filename(f"{session['socio_id']}_{referencia}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO facturas (socio_id, tipo_plan, monto, referencia, comprobante)
        VALUES (?, ?, ?, ?, ?)
    ''', (session['socio_id'], tipo_plan, monto, referencia, filename))
    conn.commit()
    conn.close()

    flash('Comprobante enviado exitosamente. Queda en espera de aprobación.')
    return redirect(url_for('perfil'))

@app.route('/admin')
def admin():
    from datetime import datetime
    conn = get_db()
    cursor = conn.cursor()
    pendientes = cursor.execute("""
        SELECT f.id, s.nombre, s.cedula, f.tipo_plan, f.monto, f.referencia, f.comprobante, f.fecha
        FROM facturas f
        JOIN socios s ON f.socio_id = s.id
        WHERE f.estado = 'Pendiente'
        ORDER BY f.id DESC
    """).fetchall()
    raw_socios = cursor.execute('SELECT * FROM socios ORDER BY id DESC').fetchall()
    conn.close()
    socios = []
    hoy = datetime.now().date()
    for s in raw_socios:
        s_dict = dict(s)
        venc_str = s_dict.get('vencimiento', '')
        dias = 0
        alerta = 'al-dia'
        try:
            venc_date = datetime.strptime(venc_str, '%Y-%m-%d').date()
            dias = (venc_date - hoy).days
            if dias < 0:
                alerta = 'vencido'
            elif dias <= 3:
                alerta = 'por-vencer'
        except:
            dias = 0
        s_dict['fecha_vencimiento'] = venc_str
        s_dict['dias'] = dias
        s_dict['alerta'] = alerta
        socios.append(s_dict)
    return render_template('admin.html', pendientes=pendientes, socios=socios)
def aprobar_pago(factura_id):
    conn = get_db()
    cursor = conn.cursor()
    factura = cursor.execute('SELECT socio_id, tipo_plan FROM facturas WHERE id = ?', (factura_id,)).fetchone()

    if factura:
        socio_id = factura['socio_id']
        tipo_plan = factura['tipo_plan']
        dias_a_sumar = 30 if tipo_plan == "Mensualidad" else 1

        socio = cursor.execute('SELECT vencimiento FROM socios WHERE id = ?', (socio_id,)).fetchone()
        venc_actual = socio['vencimiento']

        hoy = datetime.now()
        if venc_actual != 'Vencido':
            try:
                dt_venc = datetime.strptime(venc_actual, '%Y-%m-%d')
                if dt_venc > hoy:
                    nueva_fecha = dt_venc + timedelta(days=dias_a_sumar)
                else:
                    nueva_fecha = hoy + timedelta(days=dias_a_sumar)
            except ValueError:
                nueva_fecha = hoy + timedelta(days=dias_a_sumar)
        else:
            nueva_fecha = hoy + timedelta(days=dias_a_sumar)

        cursor.execute('UPDATE socios SET vencimiento = ? WHERE id = ?', (nueva_fecha.strftime('%Y-%m-%d'), socio_id))
        cursor.execute("UPDATE facturas SET estado = 'Aprobado' WHERE id = ?", (factura_id,))
        conn.commit()

    conn.close()
    return redirect(url_for('admin'))


@app.route('/eliminar_pago/<int:id>')
def eliminar_pago(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM facturas WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))

@app.route('/admin/socio/<int:id>')
def admin_socio(id):
    conn = get_db()
    cursor = conn.cursor()
    socio = cursor.execute('SELECT * FROM socios WHERE id = ?', (id,)).fetchone()
    facturas = cursor.execute('SELECT * FROM facturas WHERE socio_id = ?', (id,)).fetchall()
    conn.close()
    return render_template('admin_socio.html', socio=socio, facturas=facturas)

if __name__ == '__main__':

    app.run(host='0.0.0.0', port=5000, debug=True)
