from flask import Flask, render_template, request, jsonify
import sqlite3
import os
from datetime import datetime, timedelta

app = Flask(__name__)
DB_NAME = os.path.join(os.path.dirname(__file__), "marvin_gym.db")

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS socios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            telefono TEXT NOT NULL,
            plan TEXT NOT NULL,
            fecha_registro DATE NOT NULL,
            fecha_vencimiento DATE NOT NULL,
            monto REAL NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS gastos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            concepto TEXT NOT NULL,
            monto REAL NOT NULL,
            fecha DATE NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/admin')
def admin():
    return render_template('admin.html')

@app.route('/api/inscribir', methods=['POST'])
def inscribir():
    data = request.json
    nombre, telefono, plan = data.get('nombre'), data.get('telefono'), data.get('plan')
    monto = 25.0 if plan == 'Mensual' else 65.0
    hoy = datetime.now().date()
    vencimiento = hoy + timedelta(days=(30 if plan == 'Mensual' else 90))

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO socios (nombre, telefono, plan, fecha_registro, fecha_vencimiento, monto)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (nombre, telefono, plan, hoy, vencimiento, monto))
    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "nombre": nombre, "vencimiento": str(vencimiento)})

@app.route('/api/socios', methods=['GET'])
def obtener_socios():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT id, nombre, telefono, plan, fecha_registro, fecha_vencimiento, monto FROM socios ORDER BY fecha_vencimiento ASC')
    rows = cursor.fetchall()
    conn.close()
    
    socios = [{
        "id": r[0], "nombre": r[1], "telefono": r[2], "plan": r[3], 
        "fecha_registro": r[4], "fecha_vencimiento": r[5], "monto": r[6]
    } for r in rows]
    return jsonify(socios)

@app.route('/api/renovar/<int:socio_id>', methods=['POST'])
def renovar(socio_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT fecha_vencimiento, monto FROM socios WHERE id = ?', (socio_id,))
    socio = cursor.fetchone()
    
    if socio:
        fecha_actual = datetime.strptime(socio[0], '%Y-%m-%d').date()
        base_fecha = max(fecha_actual, datetime.now().date())
        nueva_fecha = base_fecha + timedelta(days=30)
        nuevo_monto = socio[1] + 25.0

        cursor.execute('''
            UPDATE socios SET fecha_vencimiento = ?, monto = ? WHERE id = ?
        ''', (nueva_fecha, nuevo_monto, socio_id))
        conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route('/api/gasto', methods=['POST'])
def agregar_gasto():
    data = request.json
    concepto, monto = data.get('concepto'), data.get('monto')
    hoy = datetime.now().date()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO gastos (concepto, monto, fecha) VALUES (?, ?, ?)', (concepto, monto, hoy))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route('/api/gastos', methods=['GET'])
def obtener_gastos():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT id, concepto, monto, fecha FROM gastos')
    rows = cursor.fetchall()
    conn.close()
    
    gastos = [{"id": r[0], "concepto": r[1], "monto": r[2], "fecha": r[3]} for r in rows]
    return jsonify(gastos)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
