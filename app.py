from flask import Flask, render_template, jsonify, request
from smbus2 import SMBus
from bme280 import BME280
from ltr559 import LTR559
from enviroplus import gas
from pms5003 import PMS5003
import threading
import time
import sqlite3
from datetime import datetime, timedelta

app = Flask(__name__)

# Setup sensors
bus = SMBus(1)
bme280 = BME280(i2c_dev=bus)
ltr559 = LTR559()
pms5003 = PMS5003()

DB_PATH = '/home/jakem/enviro-dashboard/readings.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS readings (
            timestamp TEXT,
            temperature REAL,
            humidity REAL,
            pressure REAL,
            light REAL,
            oxidising REAL,
            reducing REAL,
            nh3 REAL,
            pm1 REAL,
            pm25 REAL,
            pm10 REAL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

latest_data = {
    'temperature': 0, 'humidity': 0, 'pressure': 0,
    'light': 0, 'proximity': 0,
    'oxidising': 0, 'reducing': 0, 'nh3': 0,
    'pm1': 0, 'pm25': 0, 'pm10': 0
}

def read_sensors():
    last_logged = 0
    while True:
        try:
            temperature = bme280.get_temperature()
            temperature_f = (temperature * 9/5) +32
            latest_data['temperature'] = round(temperature_f -5, 1)
            latest_data['humidity'] = round(bme280.get_humidity(), 1)
            latest_data['pressure'] = round(bme280.get_pressure(), 1)

            latest_data['light'] = round(ltr559.get_lux(), 1)
            latest_data['proximity'] = ltr559.get_proximity()

            gas_data = gas.read_all()
            latest_data['oxidising'] = round(gas_data.oxidising / 1000,  2)
            latest_data['reducing'] = round(gas_data.reducing / 1000, 2)
            latest_data['nh3'] = round(gas_data.nh3 / 1000, 2)

            pm_data = pms5003.read()
            latest_data['pm1'] = pm_data.pm_ug_per_m3(1.0)
            latest_data['pm25'] = pm_data.pm_ug_per_m3(2.5)
            latest_data['pm10'] = pm_data.pm_ug_per_m3(10)

            # Log to database once per minute
            now = time.time()
            if now - last_logged >= 60:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute('''
                    INSERT INTO readings VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ''', (
                    datetime.now().isoformat(),
                    latest_data['temperature'], latest_data['humidity'], latest_data['pressure'],
                    latest_data['light'],
                    latest_data['oxidising'], latest_data['reducing'], latest_data['nh3'],
                    latest_data['pm1'], latest_data['pm25'], latest_data['pm10']
                ))
                conn.commit()
                conn.close()
                last_logged = now

        except Exception as e:
            print(f"Sensor read error: {e}")

        time.sleep(3)

sensor_thread = threading.Thread(target=read_sensors, daemon=True)
sensor_thread.start()

@app.route('/')
def index():
    return render_template('index.html', **latest_data)

@app.route('/data')
def data():
    return jsonify(latest_data)

@app.route('/history')
def history():
    # Get the time range from the request (defaults to 1 hour)
    range_arg = request.args.get('range', 'hour')
    if range_arg == 'hour':
        since = datetime.now() - timedelta(hours=1)
    elif range_arg == 'day':
        since = datetime.now() - timedelta(days=1)
    elif range_arg == 'week':
        since = datetime.now() - timedelta(days=7)
    else:
        since = datetime.now() - timedelta(hours=1)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM readings WHERE timestamp >= ? ORDER BY timestamp',
              (since.isoformat(),))
    rows = c.fetchall()
    conn.close()

    return jsonify([{
        'timestamp': r[0],
        'temperature': r[1], 'humidity': r[2], 'pressure': r[3],
        'light': r[4],
        'oxidising': r[5], 'reducing': r[6], 'nh3': r[7],
        'pm1': r[8], 'pm25': r[9], 'pm10': r[10]
    } for r in rows])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
