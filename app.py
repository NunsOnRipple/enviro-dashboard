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

# Gas sensor baselines (R0) - represents clean air resistance
# Tuned from 95th/5th percentile of historical data
GAS_BASELINES = {
    'oxidising': 42.72,
    'reducing': 403.7,
    'nh3': 124.65
}

def gas_air_quality(metric, current_value):
    """
    Returns a 0-100 score where 100 = baseline clean air, lower = more polluted.
    Returns None if can't compute.
    """
    baseline = GAS_BASELINES.get(metric)
    if baseline is None or current_value is None or current_value <= 0:
        return None
    
    if metric == 'oxidising':
        # Higher resistance = more NO2. Score drops as value rises above baseline.
        # If value == baseline → 100. If value is 2x baseline → 50. Etc.
        return round(max(0, min(100, (baseline / current_value) * 100)), 1)
    else:
        # reducing & nh3: lower resistance = more gas. Score drops as value falls.
        return round(max(0, min(100, (current_value / baseline) * 100)), 1)

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
    response = dict(latest_data)
    response['oxidising_score'] = gas_air_quality('oxidising', latest_data['oxidising'])
    response['reducing_score'] = gas_air_quality('reducing', latest_data['reducing'])
    response['nh3_score'] = gas_air_quality('nh3', latest_data['nh3'])
    return jsonify(response)

@app.route('/history')
def history():
    range_arg = request.args.get('range', 'hour')
    if range_arg == 'hour':
        since = datetime.now() - timedelta(hours=1)
        bucket_minutes = 0  # no downsampling, return raw
    elif range_arg == 'day':
        since = datetime.now() - timedelta(days=1)
        bucket_minutes = 10  # 144 points
    elif range_arg == 'week':
        since = datetime.now() - timedelta(days=7)
        bucket_minutes = 60  # 168 points
    else:
        since = datetime.now() - timedelta(hours=1)
        bucket_minutes = 0

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM readings WHERE timestamp >= ? ORDER BY timestamp',
              (since.isoformat(),))
    rows = c.fetchall()
    conn.close()

    # Helper to convert a row into a dict
    def row_to_dict(r):
        return {
            'timestamp': r[0],
            'temperature': r[1], 'humidity': r[2], 'pressure': r[3],
            'light': r[4],
            'oxidising': r[5], 'reducing': r[6], 'nh3': r[7],
            'pm1': r[8], 'pm25': r[9], 'pm10': r[10]
        }

    # No downsampling for hour view, return raw values
    if bucket_minutes == 0:
        return jsonify([{**row_to_dict(r), 'min': None, 'max': None} for r in rows])

    # Downsample: group rows into time buckets, compute min/avg/max
    metrics = ['temperature', 'humidity', 'pressure', 'light',
               'oxidising', 'reducing', 'nh3', 'pm1', 'pm25', 'pm10']

    buckets = {}
    for r in rows:
        d = row_to_dict(r)
        ts = datetime.fromisoformat(d['timestamp'])
        bucket_key = ts.replace(
            minute=(ts.minute // bucket_minutes) * bucket_minutes,
            second=0, microsecond=0
        ).isoformat()
        if bucket_key not in buckets:
            buckets[bucket_key] = []
        buckets[bucket_key].append(d)

    result = []
    for bucket_ts in sorted(buckets.keys()):
        readings = buckets[bucket_ts]
        entry = {'timestamp': bucket_ts, 'min': {}, 'max': {}}
        for m in metrics:
            vals = [r[m] for r in readings]
            entry[m] = round(sum(vals) / len(vals), 2)  # average
            entry['min'][m] = round(min(vals), 2)
            entry['max'][m] = round(max(vals), 2)
        result.append(entry)

    return jsonify(result)

@app.route('/history-view')
def history_view():
    metric = request.args.get('metric', 'temperature')
    return render_template('history.html', metric=metric)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
