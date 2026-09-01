import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'marvingym_clave_secreta_super_segura'

# Filtro para formatear números con separadores de miles
@app.template_filter('format_with_commas')
def format_with_commas(value):
    try:
        return f"{int(value):,}".replace(",", ".")
    except (ValueError, TypeError):
        return value

def obtener_tasa():
    conn = sqlite3.connect('gym.db')
    c = conn.cursor()
    c.execute("SELECT valor FROM config WHERE clave = 'tasa_dolar'")
    resultado = c.fetchone()
    conn.close()
    return float(resultado[0]) if resultado else 45.0

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('rol') != 'admin':
            flash('Acceso denegado. Se requiere ser administrador.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def socio_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('rol') != 'socio':
            flash('Acceso denegado. Se requiere ser socio.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        cedula = request.form.get('cedula')
        password = request.form.get('password')
        
        conn = sqlite3.connect('gym.db')
        c = conn.cursor()
        c.execute("SELECT id, nombre, password, cedula, estado FROM usuarios WHERE cedula = ?", (cedula,))
        usuario = c.fetchone()
        conn.close()
        
        if usuario and check_password_hash(usuario[2], password):
            if usuario[4] == 'Inactivo':
                flash('Cuenta inactiva. Contacte al administrador.', 'danger')
                return render_template('login.html')
            
            session['user_id'] = usuario[0]
            session['nombre'] = usuario[1]
            
            if usuario[3] == 'admin123':
                session['rol'] = 'admin'
                flash(f'Bienvenido administrador {usuario[1]}', 'success')
                return redirect(url_for('admin_dashboard'))
            else:
                session['rol'] = 'socio'
                flash(f'Bienvenido {usuario[1]}', 'success')
                return redirect(url_for('socio_dashboard'))
        else:
            flash('Cedula o contraseña incorrecta', 'danger')
    
    return render_template('login.html')

@app.route('/socio/dashboard')
@socio_required
def socio_dashboard():
    user_id = session.get('user_id')
    conn = sqlite3.connect('gym.db')
    c = conn.cursor()
    
    c.execute("SELECT nombre, cedula, telefono, fecha_vencimiento FROM usuarios WHERE id = ?", (user_id,))
    socio = c.fetchone()
    
    tasa = obtener_tasa()
    
    if socio:
        fecha_vencimiento = socio[3]
        hoy = datetime.now().date()
        
        if fecha_vencimiento and fecha_vencimiento != '2000-01-01':
            fecha_venc = datetime.strptime(fecha_vencimiento, '%Y-%m-%d').date()
            if fecha_venc >= hoy:
                dias_restantes = (fecha_venc - hoy).days
                estado = "Activa"
            else:
                dias_restantes = 0
                estado = "Vencida"
        else:
            dias_restantes = 0
            estado = "Sin membresia"
        
        user_data = {
            'nombre': socio[0],
            'cedula': socio[1],
            'telefono': socio[2],
            'vencimiento': socio[3],
            'estado': estado,
            'dias': dias_restantes
        }
        
        c.execute("SELECT fecha_pago, monto, metodo, estado FROM pagos WHERE socio_id = ? ORDER BY fecha_pago DESC LIMIT 5", (user_id,))
        historial_pagos = c.fetchall()
    else:
        user_data = None
        historial_pagos = []
    
    conn.close()
    return render_template('socio_dashboard.html', user=user_data, pagos=historial_pagos, tasa=tasa)

@app.route('/reportar_pago', methods=['POST'])
@socio_required
def reportar_pago():
    socio_id = session.get('user_id')
    monto = request.form.get('monto')
    metodo = request.form.get('metodo')
    referencia = request.form.get('referencia')
    
    conn = sqlite3.connect('gym.db')
    c = conn.cursor()
    
    c.execute('''
        INSERT INTO pagos (socio_id, monto, metodo, referencia, estado)
        VALUES (?, ?, ?, ?, 'Pendiente')
    ''', (socio_id, monto, metodo, referencia))
    
    conn.commit()
    conn.close()
    
    flash('Pago reportado exitosamente. El administrador lo revisara.', 'success')
    return redirect(url_for('socio_dashboard'))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    conn = sqlite3.connect('gym.db')
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM usuarios WHERE cedula != 'admin123'")
    total_socios = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM usuarios WHERE fecha_vencimiento > date('now') AND cedula != 'admin123'")
    activos = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM usuarios WHERE fecha_vencimiento <= date('now') AND fecha_vencimiento != '2000-01-01' AND cedula != 'admin123'")
    vencidos = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM pagos WHERE estado = 'Pendiente'")
    pagos_pendientes = c.fetchone()[0]
    
    tasa = obtener_tasa()
    
    c.execute("""
        SELECT p.id, u.nombre, p.monto, p.metodo, p.fecha_pago 
        FROM pagos p 
        JOIN usuarios u ON p.socio_id = u.id 
        WHERE p.estado = 'Pendiente' 
        ORDER BY p.fecha_pago DESC 
        LIMIT 10
    """)
    pagos_pendientes_lista = c.fetchall()
    
    c.execute("""
        SELECT id, nombre, cedula, telefono, fecha_vencimiento 
        FROM usuarios 
        WHERE fecha_vencimiento BETWEEN date('now') AND date('now', '+7 days') 
        AND cedula != 'admin123'
    """)
    proximos_vencer = c.fetchall()
    
    conn.close()
    
    return render_template('admin_dashboard.html', 
                         total_socios=total_socios,
                         activos=activos,
                         vencidos=vencidos,
                         pagos_pendientes=pagos_pendientes,
                         pagos_pendientes_lista=pagos_pendientes_lista,
                         proximos_vencer=proximos_vencer,
                         tasa=tasa)

@app.route('/admin/pagos')
@admin_required
def admin_pagos():
    conn = sqlite3.connect('gym.db')
    c = conn.cursor()
    
    busqueda = request.args.get('buscar', '').strip()
    
    if busqueda:
        c.execute("""
            SELECT p.id, u.nombre, u.cedula, p.monto, p.metodo, p.referencia, p.fecha_pago, p.estado 
            FROM pagos p 
            JOIN usuarios u ON p.socio_id = u.id 
            WHERE p.referencia LIKE ?
            ORDER BY p.fecha_pago DESC
        """, (f'%{busqueda}%',))
    else:
        c.execute("""
            SELECT p.id, u.nombre, u.cedula, p.monto, p.metodo, p.referencia, p.fecha_pago, p.estado 
            FROM pagos p 
            JOIN usuarios u ON p.socio_id = u.id 
            ORDER BY p.fecha_pago DESC
        """)
    
    pagos = c.fetchall()
    conn.close()
    
    tasa = obtener_tasa()
    return render_template('admin_pagos.html', pagos=pagos, tasa=tasa, busqueda=busqueda)

@app.route('/admin/aprobar_pago/<int:pago_id>', methods=['POST'])
@admin_required
def aprobar_pago(pago_id):
    opcion = request.form.get('opcion')
    
    opciones = {
        'dia': 1,
        'semana': 7,
        'mes': 30
    }
    
    dias = opciones.get(opcion, 30)
    
    conn = sqlite3.connect('gym.db')
    c = conn.cursor()
    
    c.execute("SELECT socio_id FROM pagos WHERE id = ?", (pago_id,))
    pago = c.fetchone()
    
    if pago:
        socio_id = pago[0]
        nueva_fecha = datetime.now().date() + timedelta(days=dias)
        
        c.execute("""
            UPDATE pagos 
            SET estado = 'Aprobado', fecha_aprobacion = date('now'), admin_id = ? 
            WHERE id = ?
        """, (session.get('user_id'), pago_id))
        
        c.execute("UPDATE usuarios SET fecha_vencimiento = ? WHERE id = ?", 
                 (nueva_fecha.strftime('%Y-%m-%d'), socio_id))
        
        conn.commit()
        
        texto_opcion = {'dia': '1 dia', 'semana': '7 dias', 'mes': '30 dias'}.get(opcion, '30 dias')
        flash(f'Pago aprobado. Membresia extendida por {texto_opcion}', 'success')
    else:
        flash('Pago no encontrado', 'danger')
    
    conn.close()
    return redirect(url_for('admin_pagos'))

@app.route('/admin/rechazar_pago/<int:pago_id>', methods=['POST'])
@admin_required
def rechazar_pago(pago_id):
    conn = sqlite3.connect('gym.db')
    c = conn.cursor()
    
    c.execute("UPDATE pagos SET estado = 'Rechazado' WHERE id = ?", (pago_id,))
    conn.commit()
    conn.close()
    
    flash('Pago rechazado', 'warning')
    return redirect(url_for('admin_pagos'))

@app.route('/admin/usuarios')
@admin_required
def admin_usuarios():
    conn = sqlite3.connect('gym.db')
    c = conn.cursor()
    c.execute("SELECT id, nombre, cedula, telefono, fecha_vencimiento, estado FROM usuarios WHERE cedula != 'admin123' ORDER BY id DESC")
    usuarios = c.fetchall()
    conn.close()
    return render_template('admin_usuarios.html', usuarios=usuarios)

@app.route('/admin/cambiar_estado/<int:user_id>', methods=['POST'])
@admin_required
def cambiar_estado(user_id):
    estado = request.form.get('estado')
    conn = sqlite3.connect('gym.db')
    c = conn.cursor()
    c.execute("UPDATE usuarios SET estado = ? WHERE id = ?", (estado, user_id))
    conn.commit()
    conn.close()
    flash('Estado del usuario actualizado', 'success')
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/morosos')
@admin_required
def admin_morosos():
    conn = sqlite3.connect('gym.db')
    c = conn.cursor()
    
    c.execute("""
        SELECT id, nombre, cedula, telefono, fecha_vencimiento 
        FROM usuarios 
        WHERE fecha_vencimiento < date('now') 
        AND fecha_vencimiento != '2000-01-01'
        AND cedula != 'admin123'
        ORDER BY fecha_vencimiento ASC
    """)
    morosos = c.fetchall()
    conn.close()
    
    return render_template('admin_morosos.html', morosos=morosos)

@app.route('/admin/config', methods=['GET', 'POST'])
@admin_required
def admin_config():
    if request.method == 'POST':
        nueva_tasa = request.form.get('tasa_dolar')
        
        conn = sqlite3.connect('gym.db')
        c = conn.cursor()
        c.execute("UPDATE config SET valor = ? WHERE clave = 'tasa_dolar'", (nueva_tasa,))
        conn.commit()
        conn.close()
        
        flash(f'Tasa de cambio actualizada a {nueva_tasa} Bs/USD', 'success')
        return redirect(url_for('admin_config'))
    
    tasa = obtener_tasa()
    return render_template('admin_config.html', tasa=tasa)

@app.route('/logout')
def logout():
    session.clear()
    flash('Sesion cerrada correctamente', 'success')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
