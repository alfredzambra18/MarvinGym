import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = 'marvingym_clave_secreta_super_segura'

# Filtro para formatear números con separadores de miles
@app.template_filter("format_with_commas")
def format_with_commas(value):
    try:
        return f"{int(value):,}".replace(",", ".")
    except (ValueError, TypeError):
        return value


# ⚠️ CAMBIA ESTO: Reemplaza 'TU_URL_DE_RENDER_AQUI' por la URL de tu base de datos de Render
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'postgresql://marvingym:dTbJv0KvbhOcaW7SR6LuCvLoLbIRP55U@dpg-dabk5vp42hec73a9j4c0-a.oregon-postgres.render.com/marvingym')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- MODELOS DE BASE DE DATOS (TABLAS) ---
class Usuario(db.Model):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    cedula = db.Column(db.String(20), unique=True, nullable=False)
    telefono = db.Column(db.String(20))
    password = db.Column(db.String(200), nullable=False)
    rol = db.Column(db.String(20), default='socio')  # 'admin' o 'socio'
    estado = db.Column(db.String(20), default='Activo')
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_vencimiento = db.Column(db.Date, default=datetime(2000, 1, 1).date())
    
    # Relación con pagos
    pagos = db.relationship('Pago', backref='usuario', lazy=True)

class Pago(db.Model):
    __tablename__ = 'pagos'
    id = db.Column(db.Integer, primary_key=True)
    socio_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    metodo = db.Column(db.String(50))
    referencia = db.Column(db.String(100))
    estado = db.Column(db.String(20), default='Pendiente')  # Pendiente, Aprobado, Rechazado
    fecha_pago = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_aprobacion = db.Column(db.DateTime)
    admin_id = db.Column(db.Integer)

class Config(db.Model):
    __tablename__ = 'config'
    clave = db.Column(db.String(50), primary_key=True)
    valor = db.Column(db.String(100))

# --- FUNCIONES AUXILIARES ---
def obtener_tasa():
    config = Config.query.filter_by(clave='tasa_dolar').first()
    return float(config.valor) if config else 45.0

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

# --- RUTAS ---
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        cedula = request.form.get('cedula')
        telefono = request.form.get('telefono')
        password = request.form.get('password')
        
        # Verificar si la cédula ya existe
        existe = Usuario.query.filter_by(cedula=cedula).first()
        if existe:
            flash('Esta cédula ya está registrada. Inicie sesión.', 'danger')
            return redirect(url_for('registro'))
        
        # Crear el nuevo socio
        nuevo_usuario = Usuario(
            nombre=nombre,
            cedula=cedula,
            telefono=telefono,
            password=generate_password_hash(password),
            rol='socio',
            estado='Activo'
        )
        
        db.session.add(nuevo_usuario)
        db.session.commit()
        
        flash('¡Registro exitoso! Ahora puede iniciar sesión.', 'success')
        return redirect(url_for('login'))
    
    return render_template('registro.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        cedula = request.form.get('cedula')
        password = request.form.get('password')
        
        usuario = Usuario.query.filter_by(cedula=cedula).first()
        
        if usuario and check_password_hash(usuario.password, password):
            if usuario.estado == 'Inactivo':
                flash('Cuenta inactiva. Contacte al administrador.', 'danger')
                return render_template('login.html')
            
            session['user_id'] = usuario.id
            session['nombre'] = usuario.nombre
            
            if usuario.rol == 'admin':
                session['rol'] = 'admin'
                flash(f'Bienvenido administrador {usuario.nombre}', 'success')
                return redirect(url_for('admin_dashboard'))
            else:
                session['rol'] = 'socio'
                flash(f'Bienvenido {usuario.nombre}', 'success')
                return redirect(url_for('socio_dashboard'))
        else:
            flash('Cédula o contraseña incorrecta', 'danger')
    
    return render_template('login.html')

@app.route('/socio/dashboard')
@socio_required
def socio_dashboard():
    user_id = session.get('user_id')
    socio = Usuario.query.get(user_id)
    
    tasa = obtener_tasa()
    
    if socio:
        fecha_vencimiento = socio.fecha_vencimiento
        hoy = datetime.now().date()
        
        if fecha_vencimiento and fecha_vencimiento != datetime(2000, 1, 1).date():
            if fecha_vencimiento >= hoy:
                dias_restantes = (fecha_vencimiento - hoy).days
                estado = "Activa"
            else:
                dias_restantes = 0
                estado = "Vencida"
        else:
            dias_restantes = 0
            estado = "Sin membresía"
        
        user_data = {
            'nombre': socio.nombre,
            'cedula': socio.cedula,
            'telefono': socio.telefono,
            'vencimiento': socio.fecha_vencimiento,
            'estado': estado,
            'dias': dias_restantes
        }
        
        historial_pagos = Pago.query.filter_by(socio_id=user_id).order_by(Pago.fecha_pago.desc()).limit(5).all()
    else:
        user_data = None
        historial_pagos = []
    
    return render_template('socio_dashboard.html', user=user_data, pagos=historial_pagos, tasa=tasa)

@app.route('/reportar_pago', methods=['POST'])
@socio_required
def reportar_pago():
    socio_id = session.get('user_id')
    monto = request.form.get('monto')
    metodo = request.form.get('metodo')
    referencia = request.form.get('referencia')
    
    nuevo_pago = Pago(
        socio_id=socio_id,
        monto=float(monto),
        metodo=metodo,
        referencia=referencia,
        estado='Pendiente'
    )
    
    db.session.add(nuevo_pago)
    db.session.commit()
    
    flash('Pago reportado exitosamente. El administrador lo revisará.', 'success')
    return redirect(url_for('socio_dashboard'))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    total_socios = Usuario.query.filter_by(rol='socio').count()
    activos = Usuario.query.filter(Usuario.rol=='socio', Usuario.fecha_vencimiento > datetime.now().date()).count()
    vencidos = Usuario.query.filter(Usuario.rol=='socio', Usuario.fecha_vencimiento <= datetime.now().date(), Usuario.fecha_vencimiento != datetime(2000, 1, 1).date()).count()
    pagos_pendientes = Pago.query.filter_by(estado='Pendiente').count()
    tasa = obtener_tasa()
    
    pagos_pendientes_lista = Pago.query.filter_by(estado='Pendiente').order_by(Pago.fecha_pago.desc()).limit(10).all()
    
    # Socios que vencen en los próximos 7 días
    fecha_limite = datetime.now().date() + timedelta(days=7)
    proximos_vencer = Usuario.query.filter(
        Usuario.rol=='socio',
        Usuario.fecha_vencimiento >= datetime.now().date(),
        Usuario.fecha_vencimiento <= fecha_limite
    ).all()
    
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
    busqueda = request.args.get('buscar', '').strip()
    
    if busqueda:
        pagos = Pago.query.join(Usuario).filter(Pago.referencia.like(f'%{busqueda}%')).order_by(Pago.fecha_pago.desc()).all()
    else:
        pagos = Pago.query.order_by(Pago.fecha_pago.desc()).all()
    
    tasa = obtener_tasa()
    return render_template('admin_pagos.html', pagos=pagos, tasa=tasa, busqueda=busqueda)

@app.route('/admin/aprobar_pago/<int:pago_id>', methods=['POST'])
@admin_required
def aprobar_pago(pago_id):
    opcion = request.form.get('opcion')
    opciones = {'dia': 1, 'semana': 7, 'mes': 30}
    dias = opciones.get(opcion, 30)
    
    pago = Pago.query.get(pago_id)
    
    if pago:
        socio_id = pago.socio_id
        nueva_fecha = datetime.now().date() + timedelta(days=dias)
        
        pago.estado = 'Aprobado'
        pago.fecha_aprobacion = datetime.utcnow()
        pago.admin_id = session.get('user_id')
        
        socio = Usuario.query.get(socio_id)
        socio.fecha_vencimiento = nueva_fecha
        
        db.session.commit()
        
        texto_opcion = {'dia': '1 día', 'semana': '7 días', 'mes': '30 días'}.get(opcion, '30 días')
        flash(f'Pago aprobado. Membresía extendida por {texto_opcion}', 'success')
    else:
        flash('Pago no encontrado', 'danger')
    
    return redirect(url_for('admin_pagos'))

@app.route('/admin/rechazar_pago/<int:pago_id>', methods=['POST'])
@admin_required
def rechazar_pago(pago_id):
    pago = Pago.query.get(pago_id)
    if pago:
        pago.estado = 'Rechazado'
        db.session.commit()
        flash('Pago rechazado', 'warning')
    
    return redirect(url_for('admin_pagos'))

@app.route('/admin/usuarios')
@admin_required
def admin_usuarios():
    usuarios = Usuario.query.filter_by(rol='socio').order_by(Usuario.id.desc()).all()
    return render_template('admin_usuarios.html', usuarios=usuarios)

@app.route('/admin/cambiar_estado/<int:user_id>', methods=['POST'])
@admin_required
def cambiar_estado(user_id):
    estado = request.form.get('estado')
    usuario = Usuario.query.get(user_id)
    if usuario:
        usuario.estado = estado
        db.session.commit()
        flash('Estado del usuario actualizado', 'success')
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/morosos')
@admin_required
def admin_morosos():
    morosos = Usuario.query.filter(
        Usuario.rol=='socio',
        Usuario.fecha_vencimiento < datetime.now().date(),
        Usuario.fecha_vencimiento != datetime(2000, 1, 1).date()
    ).order_by(Usuario.fecha_vencimiento.asc()).all()
    
    return render_template('admin_morosos.html', morosos=morosos)

@app.route('/admin/config', methods=['GET', 'POST'])
@admin_required
def admin_config():
    if request.method == 'POST':
        nueva_tasa = request.form.get('tasa_dolar')
        config = Config.query.filter_by(clave='tasa_dolar').first()
        if config:
            config.valor = nueva_tasa
        else:
            config = Config(clave='tasa_dolar', valor=nueva_tasa)
            db.session.add(config)
        
        db.session.commit()
        flash(f'Tasa de cambio actualizada a {nueva_tasa} Bs/USD', 'success')
        return redirect(url_for('admin_config'))
    
    tasa = obtener_tasa()
    return render_template('admin_config.html', tasa=tasa)

@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada correctamente', 'success')
    return redirect(url_for('login'))

# Crear tablas y admin inicial si no existen
with app.app_context():
    db.create_all()
    
    # Crear admin por defecto si no existe
    if not Usuario.query.filter_by(cedula='admin123').first():
        admin = Usuario(
            nombre='Administrador',
            cedula='admin123',
            password=generate_password_hash('admin123'),
            rol='admin',
            estado='Activo'
        )
        db.session.add(admin)
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')


