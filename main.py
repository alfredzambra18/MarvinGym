import os
import sqlite3
import urllib.parse
import re
import uuid
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response, abort
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import logging

app = Flask(__name__)

# Configuración desde variables de entorno
app.secret_key = os.environ.get('SECRET_KEY', 'clave_temporal_insegura_123')
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', 'static/uploads')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2 MB máximo
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Crear carpeta de uploads
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Variables desde entorno
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
PAGO_MOVIL = {
    "banco": os.environ.get('BANCO', "Banco Nacional de Crédito (BNC)"),
    "cedula": os.environ.get('CEDULA', "13.210.442"),
    "telefono": os.environ.get('TELEFONO', "04123931166")
}
ADMIN_WHATSAPP = os.environ.get('ADMIN_WHATSAPP', "584123931166")

# Base de datos SQLite (con soporte para disco persistente)
SQLITE_DB = os.environ.get('SQLITE_DB', 'database.db')

def get_db():
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    return conn

DB_TYPE = 'sqlite'

# ---------- Helpers de CSRF ----------
def generate_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = uuid.uuid4().hex
    return session['_csrf_token']

def validate_csrf():
    token = session.pop('_csrf_token', None)
    form_token = request.form.get('csrf_token')
    if not token or token != form_token:
        abort(403)

app.jinja_env.globals['csrf_token'] = generate_csrf_token

# ---------- Manejo de errores ----------
@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, mensaje="Página no encontrada"), 404

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Error 500: {e}")
    return render_template('error.html', code=500, mensaje="Error interno del servidor"), 500

@app.errorhandler(413)
def too_large(e):
    flash('El archivo es demasiado grande (máximo 2 MB).')
    return redirect(request.referrer or url_for('perfil'))

# ---------- Inicialización de la base de datos ----------
def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS socios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            cedula TEXT UNIQUE NOT NULL,
            telefono TEXT NOT NULL,
            email TEXT,
            fecha_nacimiento TEXT,
            password_hash TEXT NOT NULL DEFAULT 'temporal',
            vencimiento TEXT DEFAULT 'Vencido'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS planes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            duracion_dias INTEGER NOT NULL,
            precio REAL NOT NULL,
            activo INTEGER DEFAULT 1
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
    cursor.execute('SELECT COUNT(*) FROM planes')
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO planes (nombre, duracion_dias, precio) VALUES ('Pase Diario', 1, 1.0)")
        cursor.execute("INSERT INTO planes (nombre, duracion_dias, precio) VALUES ('Mensualidad', 30, 10.0)")
    conn.commit()
    conn.close()

try:
    init_db()
except Exception as e:
    logger.critical(f"Error al inicializar la base de datos: {e}")

# ---------- Validaciones ----------
def validar_cedula(cedula):
    return bool(re.match(r'^[VvEe]?\d{6,8}$', cedula))

def validar_telefono(telefono):
    return bool(re.match(r'^\+?\d{10,15}$', telefono))

def validar_email(email):
    if not email:
        return True
    return bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email))

# ---------- Rutas ----------
@app.route('/')
def index():
    if 'socio_id' in session:
        return redirect(url_for('perfil'))
    return redirect(url_for('login'))

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        validate_csrf()
        nombre = request.form['nombre'].strip()
        cedula = request.form['cedula'].strip().upper()
        telefono = request.form['telefono'].strip()
        email = request.form.get('email', '').strip()
        fecha_nacimiento = request.form.get('fecha_nacimiento', '').strip()
        password = request.form.get('password', '').strip()

        if not nombre or len(nombre) > 100:
            flash('Nombre inválido.')
        elif not validar_cedula(cedula):
            flash('Cédula inválida. Formato: V12345678 (6-8 dígitos, letra opcional V/E).')
        elif not validar_telefono(telefono):
            flash('Teléfono inválido. Debe contener solo números y al menos 10 dígitos.')
        elif not validar_email(email):
            flash('Email inválido.')
        elif len(password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres.')
        else:
            try:
                hashed_pw = generate_password_hash(password)
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO socios (nombre, cedula, telefono, email, fecha_nacimiento, password_hash) 
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (nombre, cedula, telefono, email, fecha_nacimiento, hashed_pw))
                conn.commit()
                socio_id = cursor.lastrowid
                conn.close()
                session['socio_id'] = socio_id
                session['socio_nombre'] = nombre
                return redirect(url_for('perfil'))
            except sqlite3.IntegrityError:
                flash('Esta cédula ya está registrada. Intenta iniciar sesión.')
                return redirect(url_for('login'))
            except Exception as e:
                logger.error(f"Error en registro: {e}")
                flash('Error al registrar. Verifica los datos.')
                return redirect(url_for('registro'))

    return render_template('registro.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'socio_id' in session:
        return redirect(url_for('perfil'))

    if request.method == 'POST':
        validate_csrf()
        usuario = request.form['usuario'].strip()
        password = request.form['password'].strip()
        
        conn = get_db()
        cursor = conn.cursor()
        socio = cursor.execute('SELECT * FROM socios WHERE cedula = ? OR nombre = ? OR telefono = ?', (usuario, usuario, usuario)).fetchone()
        conn.close()

        if socio:
            try:
                if check_password_hash(socio['password_hash'], password):
                    session.permanent = True
                    session['socio_id'] = socio['id']
                    session['socio_nombre'] = socio['nombre']
                    return redirect(url_for('perfil'))
                else:
                    flash('Usuario o contraseña incorrectos.')
                    return redirect(url_for('login'))
            except ValueError:
                logger.error("Hash de contraseña inválido para socio ID %s", socio['id'])
                flash('Error en la contraseña almacenada. Contacta al administrador.')
                return redirect(url_for('login'))
        else:
            flash('Usuario o contraseña incorrectos.')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/recuperar', methods=['GET', 'POST'])
def recuperar():
    if request.method == 'POST':
        validate_csrf()
        cedula = request.form['cedula'].strip().upper()
        telefono = request.form['telefono'].strip()
        nueva_password = request.form['nueva_password'].strip()

        if not validar_cedula(cedula):
            flash('Cédula inválida.')
            return redirect(url_for('recuperar'))
        if not validar_telefono(telefono):
            flash('Teléfono inválido.')
            return redirect(url_for('recuperar'))
        if len(nueva_password) < 6:
            flash('La nueva contraseña debe tener al menos 6 caracteres.')
            return redirect(url_for('recuperar'))

        conn = get_db()
        cursor = conn.cursor()
        socio = cursor.execute('SELECT * FROM socios WHERE cedula = ? AND telefono = ?', (cedula, telefono)).fetchone()
        if not socio:
            flash('No se encontró un socio con esa cédula y teléfono.')
            conn.close()
            return redirect(url_for('recuperar'))

        hashed = generate_password_hash(nueva_password)
        cursor.execute('UPDATE socios SET password_hash = ? WHERE id = ?', (hashed, socio['id']))
        conn.commit()
        conn.close()
        flash('Contraseña actualizada correctamente. Ya puedes iniciar sesión.')
        return redirect(url_for('login'))

    return render_template('recuperar.html')

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
    if not socio:
        session.clear()
        conn.close()
        return redirect(url_for('login'))

    facturas = cursor.execute('''
        SELECT tipo_plan, monto, referencia, estado, fecha 
        FROM facturas 
        WHERE socio_id = ? 
        ORDER BY id DESC
    ''', (session['socio_id'],)).fetchall()
    planes = cursor.execute('SELECT * FROM planes WHERE activo = 1').fetchall()
    conn.close()

    venc_str = socio['vencimiento']
    dias_restantes = 0
    estado_membresia = "VENCIDA"

    if venc_str != 'Vencido':
        try:
            venc_dt = datetime.strptime(venc_str, '%Y-%m-%d')
            dias_restantes = (venc_dt - datetime.now()).days
            if dias_restantes > 0:
                estado_membresia = "ACTIVA"
            else:
                dias_restantes = 0
                estado_membresia = "VENCIDA"
        except ValueError:
            pass

    user_data = {
        "nombre": socio['nombre'],
        "cedula": socio['cedula'],
        "telefono": socio['telefono'],
        "vencimiento": venc_str,
        "dias": dias_restantes,
        "estado": estado_membresia
    }

    return render_template('perfil.html', user=user_data, pago_movil=PAGO_MOVIL, facturas=facturas, planes=planes)

@app.route('/reportar_pago', methods=['POST'])
def reportar_pago():
    if 'socio_id' not in session:
        return redirect(url_for('login'))
    validate_csrf()

    plan_nombre = request.form['tipo_plan']
    referencia = request.form['referencia'].strip()
    file = request.files.get('comprobante')

    if not referencia:
        flash('La referencia es obligatoria.')
        return redirect(url_for('perfil'))

    conn = get_db()
    cursor = conn.cursor()
    plan_info = cursor.execute('SELECT precio FROM planes WHERE nombre = ?', (plan_nombre,)).fetchone()
    monto = plan_info['precio'] if plan_info else 10.0

    filename = ""
    if file and file.filename != '':
        allowed_ext = {'.jpg', '.jpeg', '.png', '.pdf'}
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in allowed_ext:
            flash('Formato de archivo no permitido. Use JPG, PNG o PDF.')
            conn.close()
            return redirect(url_for('perfil'))
        unique_name = f"{session['socio_id']}_{uuid.uuid4().hex}{ext}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_name))
        filename = unique_name

    cursor.execute('''
        INSERT INTO facturas (socio_id, tipo_plan, monto, referencia, comprobante, estado)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (session['socio_id'], plan_nombre, monto, referencia, filename, 'Pendiente'))
    conn.commit()
    conn.close()

    mensaje = f"¡Hola! Reporté un pago en MarvinGym.\n*Cliente:* {session['socio_nombre']}\n*Plan:* {plan_nombre}\n*Monto:* ${monto:.2f}\n*Referencia:* {referencia}"
    ws_url = f"https://wa.me/{ADMIN_WHATSAPP}?text={urllib.parse.quote(mensaje)}"

    return render_template('pago_reportado.html', whatsapp_url=ws_url)

# ---------- ADMIN ----------
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST' and 'clave_admin' in request.form:
        validate_csrf()
        if request.form['clave_admin'] == ADMIN_PASSWORD:
            session['es_admin'] = True
            return redirect(url_for('admin'))
        else:
            flash('Contraseña de administrador incorrecta.')
            return redirect(url_for('admin'))

    if not session.get('es_admin'):
        return render_template('admin_login.html')

    conn = get_db()
    cursor = conn.cursor()
    
    pendientes = cursor.execute("""
        SELECT f.id, s.nombre, s.cedula, s.telefono, f.tipo_plan, f.monto, f.referencia, f.comprobante, f.fecha
        FROM facturas f
        JOIN socios s ON f.socio_id = s.id
        WHERE f.estado = 'Pendiente'
        ORDER BY f.id DESC
    """).fetchall()
    
    raw_socios = cursor.execute('SELECT * FROM socios ORDER BY id DESC').fetchall()
    planes = cursor.execute('SELECT * FROM planes ORDER BY id ASC').fetchall()
    
    total_ingresos = cursor.execute("SELECT SUM(monto) FROM facturas WHERE estado = 'Aprobado'").fetchone()[0] or 0.0
    total_pendientes_monto = cursor.execute("SELECT SUM(monto) FROM facturas WHERE estado = 'Pendiente'").fetchone()[0] or 0.0
    conn.close()

    socios = []
    hoy = datetime.now().date()
    cant_activos = 0
    cant_vencidos = 0

    for s in raw_socios:
        s_dict = {key: s[key] for key in s.keys()}
        venc_str = s_dict.get('vencimiento', '')
        dias = 0
        alerta = 'al-dia'
        
        try:
            venc_date = datetime.strptime(venc_str, '%Y-%m-%d').date()
            dias = (venc_date - hoy).days
            if dias <= 0:
                alerta = 'vencido'
                cant_vencidos += 1
            elif dias <= 3:
                alerta = 'por-vencer'
                cant_activos += 1
            else:
                cant_activos += 1
        except Exception:
            dias = 0
            alerta = 'vencido'
            cant_vencidos += 1

        s_dict['fecha_vencimiento'] = venc_str
        s_dict['dias'] = dias
        s_dict['alerta'] = alerta
        s_dict['telefono'] = s_dict['telefono']
        socios.append(s_dict)

    resumen = {
        "ingresos": total_ingresos,
        "por_cobrar": total_pendientes_monto,
        "activos": cant_activos,
        "deudores": cant_vencidos
    }

    return render_template('admin.html', pendientes=pendientes, socios=socios, planes=planes, resumen=resumen)

@app.route('/admin/socio/<int:socio_id>')
def detalle_socio(socio_id):
    if not session.get('es_admin'):
        return redirect(url_for('admin'))
    try:
        conn = get_db()
        cursor = conn.cursor()
        socio = cursor.execute('SELECT * FROM socios WHERE id = ?', (socio_id,)).fetchone()
        if not socio:
            flash('Socio no encontrado.')
            conn.close()
            return redirect(url_for('admin'))
        pagos = cursor.execute('''
            SELECT tipo_plan, monto, referencia, comprobante, estado, fecha 
            FROM facturas 
            WHERE socio_id = ? 
            ORDER BY id DESC
        ''', (socio_id,)).fetchall()
        conn.close()
        return render_template('detalle_socio.html', socio=socio, pagos=pagos)
    except Exception as e:
        logger.error(f"Error en detalle_socio: {e}")
        flash('Ocurrió un error al cargar el socio.')
        return redirect(url_for('admin'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('es_admin', None)
    return redirect(url_for('admin'))

@app.route('/admin/pago_manual', methods=['POST'])
def pago_manual():
    if not session.get('es_admin'):
        return redirect(url_for('admin'))
    validate_csrf()

    socio_id = request.form['socio_id']
    plan_nombre = request.form['tipo_plan']
    referencia = request.form.get('referencia', 'EFECTIVO/TAQUILLA').strip()

    conn = get_db()
    cursor = conn.cursor()
    plan_info = cursor.execute('SELECT precio, duracion_dias FROM planes WHERE nombre = ?', (plan_nombre,)).fetchone()
    if not plan_info:
        flash('Plan no válido.')
        conn.close()
        return redirect(url_for('admin'))
    monto = plan_info['precio']
    dias_a_sumar = plan_info['duracion_dias']

    cursor.execute('''
        INSERT INTO facturas (socio_id, tipo_plan, monto, referencia, estado)
        VALUES (?, ?, ?, ?, 'Aprobado')
    ''', (socio_id, plan_nombre, monto, referencia))

    socio = cursor.execute('SELECT vencimiento FROM socios WHERE id = ?', (socio_id,)).fetchone()
    if not socio:
        flash('Socio no encontrado.')
        conn.rollback()
        conn.close()
        return redirect(url_for('admin'))
    venc_actual = socio['vencimiento']
    hoy = datetime.now()

    if venc_actual != 'Vencido':
        try:
            dt_venc = datetime.strptime(venc_actual, '%Y-%m-%d')
            nueva_fecha = (dt_venc + timedelta(days=dias_a_sumar)) if dt_venc > hoy else (hoy + timedelta(days=dias_a_sumar))
        except ValueError:
            nueva_fecha = hoy + timedelta(days=dias_a_sumar)
    else:
        nueva_fecha = hoy + timedelta(days=dias_a_sumar)

    cursor.execute('UPDATE socios SET vencimiento = ? WHERE id = ?', (nueva_fecha.strftime('%Y-%m-%d'), socio_id))
    conn.commit()
    conn.close()

    flash('Pago registrado y membresía activada correctamente.')
    return redirect(url_for('admin'))

@app.route('/admin/plan/nuevo', methods=['POST'])
def nuevo_plan():
    if not session.get('es_admin'):
        return redirect(url_for('admin'))
    validate_csrf()
        
    nombre = request.form['nombre'].strip()
    duracion = int(request.form['duracion_dias'])
    precio = float(request.form['precio'])

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO planes (nombre, duracion_dias, precio) VALUES (?, ?, ?)', (nombre, duracion, precio))
    conn.commit()
    conn.close()
    
    flash('Plan agregado exitosamente.')
    return redirect(url_for('admin'))

@app.route('/admin/aprobar/<int:factura_id>')
def aprobar_pago(factura_id):
    if not session.get('es_admin'):
        return redirect(url_for('admin'))

    conn = get_db()
    cursor = conn.cursor()
    factura = cursor.execute('SELECT socio_id, tipo_plan FROM facturas WHERE id = ?', (factura_id,)).fetchone()

    if factura:
        socio_id = factura['socio_id']
        tipo_plan = factura['tipo_plan']
        
        plan_info = cursor.execute('SELECT duracion_dias FROM planes WHERE nombre = ?', (tipo_plan,)).fetchone()
        dias_a_sumar = plan_info['duracion_dias'] if plan_info else 30

        socio = cursor.execute('SELECT vencimiento FROM socios WHERE id = ?', (socio_id,)).fetchone()
        if socio:
            venc_actual = socio['vencimiento']
            hoy = datetime.now()

            if venc_actual != 'Vencido':
                try:
                    dt_venc = datetime.strptime(venc_actual, '%Y-%m-%d')
                    nueva_fecha = (dt_venc + timedelta(days=dias_a_sumar)) if dt_venc > hoy else (hoy + timedelta(days=dias_a_sumar))
                except ValueError:
                    nueva_fecha = hoy + timedelta(days=dias_a_sumar)
            else:
                nueva_fecha = hoy + timedelta(days=dias_a_sumar)

            cursor.execute('UPDATE socios SET vencimiento = ? WHERE id = ?', (nueva_fecha.strftime('%Y-%m-%d'), socio_id))
            cursor.execute("UPDATE facturas SET estado = 'Aprobado' WHERE id = ?", (factura_id,))
            conn.commit()

    conn.close()
    return redirect(url_for('admin'))

@app.route('/admin/eliminar_socio/<int:socio_id>', methods=['POST'])
def eliminar_socio(socio_id):
    if not session.get('es_admin'):
        return redirect(url_for('admin'))
    validate_csrf()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM facturas WHERE socio_id = ?', (socio_id,))
    cursor.execute('DELETE FROM socios WHERE id = ?', (socio_id,))
    conn.commit()
    conn.close()
    flash('Socio eliminado correctamente.')
    return redirect(url_for('admin'))

@app.route('/eliminar_pago/<int:id>')
def eliminar_pago(id):
    if not session.get('es_admin'):
        return redirect(url_for('admin'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM facturas WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))

if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=5000, debug=debug)
