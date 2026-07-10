import base64
import csv
import io
import serial
import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
import plotly.graph_objs as go
import threading
from collections import deque
from datetime import datetime
import math
import re
import time
import glob
import os

# Serial config
SERIAL_PORTS = ['/dev/ttyACM1']
BAUD_RATE = 115200

# Data storage (thread-safe with deque)
MAX_POINTS = 500
RECORDINGS_DIR = 'recordings'
TELEMETRY_FIELDS = [
    'timestamp',
    'lat',
    'lon',
    'speed',
    'alt',
    'sats',
    'fix',
    'rpm',
    'engine_temp',
    'tps',
    'oil_pressure',
    'fuel_pressure',
    'brake_pressure',
    'battery_voltage',
    'wheel_speed_fr',
    'wheel_speed_fl',
    'wheel_speed_rr',
    'wheel_speed_rl',
    'g_force_lateral',
    'heading',
    'rssi',
    'snr',
    'tx_count',
    'can_frame_count',
]
telemetry_data = {
    'latitude': deque(maxlen=MAX_POINTS),
    'longitude': deque(maxlen=MAX_POINTS),
    'speed_kph': deque(maxlen=MAX_POINTS),
    'altitude': deque(maxlen=MAX_POINTS),
    'satellites': deque(maxlen=MAX_POINTS),
    'rpm': deque(maxlen=MAX_POINTS),
    'engine_temp': deque(maxlen=MAX_POINTS),
    'tps': deque(maxlen=MAX_POINTS),
    'oil_pressure': deque(maxlen=MAX_POINTS),
    'fuel_pressure': deque(maxlen=MAX_POINTS),
    'brake_pressure': deque(maxlen=MAX_POINTS),
    'battery_voltage': deque(maxlen=MAX_POINTS),
    'wheel_speed_fr': deque(maxlen=MAX_POINTS),
    'wheel_speed_fl': deque(maxlen=MAX_POINTS),
    'wheel_speed_rr': deque(maxlen=MAX_POINTS),
    'wheel_speed_rl': deque(maxlen=MAX_POINTS),
    'g_force_lateral': deque(maxlen=MAX_POINTS),
    'heading': deque(maxlen=MAX_POINTS),
    'rssi': deque(maxlen=MAX_POINTS),
    'snr': deque(maxlen=MAX_POINTS),
    'tx_count': deque(maxlen=MAX_POINTS),
    'can_frame_count': deque(maxlen=MAX_POINTS),
    'timestamps': deque(maxlen=MAX_POINTS),
}
latest = {
    'lat': None,
    'lon': None,
    'speed': None,
    'alt': None,
    'sats': None,
    'fix': None,
    'rpm': None,
    'engine_temp': None,
    'tps': None,
    'oil_pressure': None,
    'fuel_pressure': None,
    'brake_pressure': None,
    'battery_voltage': None,
    'wheel_speed_fr': None,
    'wheel_speed_fl': None,
    'wheel_speed_rr': None,
    'wheel_speed_rl': None,
    'g_force_lateral': None,
    'heading': None,
    'rssi': None,
    'snr': None,
    'tx_count': None,
    'can_frame_count': None,
    'rx_count': 0,
    'rx_total': 0,
}
serial_status = {'connected': False, 'port': None, 'last_packet_at': 0}
serial_status['last_packet_received_at'] = None
app_state = {
    'mode': 'live',
    'recording': False,
    'recording_path': None,
    'replay_rows': [],
    'replay_index': 0,
    'replay_paused': True,
    'replay_speed': 1,
    'replay_filename': None,
}
state_lock = threading.Lock()

MAX_GPS_JUMP_KM = 5.0


def fmt_float(value, precision=1, suffix=''):
    if value is None:
        return '--'
    return f"{value:.{precision}f}{suffix}"


def fmt_int(value, suffix=''):
    if value is None:
        return '--'
    return f"{int(value)}{suffix}"


def fmt_bool(value):
    if value is None:
        return '--'
    return 'Valid' if value else 'No Fix'


def stat_row(label, value):
    return html.Div([
        html.Div(label, style={'color': '#8a93a6', 'fontSize': '0.85rem'}),
        html.Div(value, style={'color': '#f5f7fb', 'fontSize': '1.05rem', 'fontWeight': '600'}),
    ], style={'display': 'flex', 'justifyContent': 'space-between', 'gap': '1rem', 'padding': '0.35rem 0'})


def section_card(title, rows):
    return html.Div([
        html.H3(title, style={'margin': '0 0 0.75rem 0', 'fontSize': '1rem', 'color': '#e9edf5'}),
        html.Div(rows, role='list')
    ], style={
        'backgroundColor': '#161c29',
        'border': '1px solid #273043',
        'borderRadius': '12px',
        'padding': '1rem',
        'boxShadow': '0 4px 18px rgba(0, 0, 0, 0.2)',
        'minWidth': '0',
    })


def parse_keyed_value(line, pattern, caster=float):
    match = re.search(pattern, line)
    if not match:
        return None
    return caster(match.group(1))


def haversine_km(lat1, lon1, lat2, lon2):
    radius_km = 6371.0
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    return 2 * radius_km * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def gps_reading_is_plausible(lat, lon):
    if lat is None or lon is None:
        return False
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return False
    if lat == 0 and lon == 0:
        return False

    previous_lat = latest['lat']
    previous_lon = latest['lon']
    if previous_lat is None or previous_lon is None:
        return True

    return haversine_km(previous_lat, previous_lon, lat, lon) <= MAX_GPS_JUMP_KM


def ensure_recordings_dir():
    os.makedirs(RECORDINGS_DIR, exist_ok=True)


def make_recording_path():
    ensure_recordings_dir()
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return os.path.join(RECORDINGS_DIR, f'telemetry_{stamp}.csv')


def reset_telemetry_buffers():
    for key in telemetry_data:
        telemetry_data[key].clear()
    latest['rx_count'] = 0


def snapshot_latest(timestamp=None):
    return {
        'timestamp': timestamp if timestamp is not None else time.time(),
        'lat': latest['lat'],
        'lon': latest['lon'],
        'speed': latest['speed'],
        'alt': latest['alt'],
        'sats': latest['sats'],
        'fix': latest['fix'],
        'rpm': latest['rpm'],
        'engine_temp': latest['engine_temp'],
        'tps': latest['tps'],
        'oil_pressure': latest['oil_pressure'],
        'fuel_pressure': latest['fuel_pressure'],
        'brake_pressure': latest['brake_pressure'],
        'battery_voltage': latest['battery_voltage'],
        'wheel_speed_fr': latest['wheel_speed_fr'],
        'wheel_speed_fl': latest['wheel_speed_fl'],
        'wheel_speed_rr': latest['wheel_speed_rr'],
        'wheel_speed_rl': latest['wheel_speed_rl'],
        'g_force_lateral': latest['g_force_lateral'],
        'heading': latest['heading'],
        'rssi': latest['rssi'],
        'snr': latest['snr'],
        'tx_count': latest['tx_count'],
        'can_frame_count': latest['can_frame_count'],
    }


def apply_sample(sample, count_rx_total=False, append_to_buffer=True):
    latest['lat'] = sample.get('lat')
    latest['lon'] = sample.get('lon')
    latest['speed'] = sample.get('speed')
    latest['alt'] = sample.get('alt')
    latest['sats'] = sample.get('sats')
    latest['fix'] = sample.get('fix')
    latest['rpm'] = sample.get('rpm')
    latest['engine_temp'] = sample.get('engine_temp')
    latest['tps'] = sample.get('tps')
    latest['oil_pressure'] = sample.get('oil_pressure')
    latest['fuel_pressure'] = sample.get('fuel_pressure')
    latest['brake_pressure'] = sample.get('brake_pressure')
    latest['battery_voltage'] = sample.get('battery_voltage')
    latest['wheel_speed_fr'] = sample.get('wheel_speed_fr')
    latest['wheel_speed_fl'] = sample.get('wheel_speed_fl')
    latest['wheel_speed_rr'] = sample.get('wheel_speed_rr')
    latest['wheel_speed_rl'] = sample.get('wheel_speed_rl')
    latest['g_force_lateral'] = sample.get('g_force_lateral')
    latest['heading'] = sample.get('heading')
    latest['rssi'] = sample.get('rssi')
    latest['snr'] = sample.get('snr')
    latest['tx_count'] = sample.get('tx_count')
    latest['can_frame_count'] = sample.get('can_frame_count')

    if append_to_buffer:
        telemetry_data['latitude'].append(sample.get('lat'))
        telemetry_data['longitude'].append(sample.get('lon'))
        telemetry_data['speed_kph'].append(sample.get('speed'))
        telemetry_data['altitude'].append(sample.get('alt'))
        telemetry_data['satellites'].append(sample.get('sats'))
        telemetry_data['rpm'].append(sample.get('rpm'))
        telemetry_data['engine_temp'].append(sample.get('engine_temp'))
        telemetry_data['tps'].append(sample.get('tps'))
        telemetry_data['oil_pressure'].append(sample.get('oil_pressure'))
        telemetry_data['fuel_pressure'].append(sample.get('fuel_pressure'))
        telemetry_data['brake_pressure'].append(sample.get('brake_pressure'))
        telemetry_data['battery_voltage'].append(sample.get('battery_voltage'))
        telemetry_data['wheel_speed_fr'].append(sample.get('wheel_speed_fr'))
        telemetry_data['wheel_speed_fl'].append(sample.get('wheel_speed_fl'))
        telemetry_data['wheel_speed_rr'].append(sample.get('wheel_speed_rr'))
        telemetry_data['wheel_speed_rl'].append(sample.get('wheel_speed_rl'))
        telemetry_data['g_force_lateral'].append(sample.get('g_force_lateral'))
        telemetry_data['heading'].append(sample.get('heading'))
        telemetry_data['rssi'].append(sample.get('rssi'))
        telemetry_data['snr'].append(sample.get('snr'))
        telemetry_data['tx_count'].append(sample.get('tx_count'))
        telemetry_data['can_frame_count'].append(sample.get('can_frame_count'))
        telemetry_data['timestamps'].append(sample.get('timestamp'))
        latest['rx_count'] = len(telemetry_data['timestamps'])

    if count_rx_total:
        latest['rx_total'] += 1


def write_recording_row(sample):
    if not app_state['recording'] or not app_state['recording_path']:
        return

    ensure_recordings_dir()
    file_exists = os.path.exists(app_state['recording_path'])
    with open(app_state['recording_path'], 'a', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=TELEMETRY_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(sample)


def load_replay_csv(contents):
    _, encoded = contents.split(',', 1)
    data = base64.b64decode(encoded)
    text = io.StringIO(data.decode('utf-8-sig'))
    reader = csv.DictReader(text)
    rows = []
    for row in reader:
        parsed = {}
        for field in TELEMETRY_FIELDS:
            value = row.get(field)
            if value in (None, ''):
                parsed[field] = None
            elif field == 'timestamp':
                parsed[field] = float(value)
            elif field == 'fix':
                parsed[field] = value.strip().lower() in ('1', 'true', 'valid', 'yes')
            elif field in ('sats', 'rpm', 'wheel_speed_fr', 'wheel_speed_fl', 'wheel_speed_rr', 'wheel_speed_rl', 'rssi', 'snr', 'tx_count', 'can_frame_count'):
                parsed[field] = int(float(value))
            else:
                parsed[field] = float(value)
        rows.append(parsed)
    return rows


def replay_step():
    if app_state['mode'] != 'replay' or app_state['replay_paused'] or not app_state['replay_rows']:
        return

    step = max(1, int(app_state['replay_speed']))
    next_index = min(app_state['replay_index'] + step, len(app_state['replay_rows']))
    if next_index <= app_state['replay_index']:
        return

    if app_state['replay_index'] == 0:
        reset_telemetry_buffers()

    for index in range(app_state['replay_index'], next_index):
        apply_sample(app_state['replay_rows'][index], count_rx_total=False, append_to_buffer=True)

    app_state['replay_index'] = next_index
    if app_state['replay_index'] >= len(app_state['replay_rows']):
        app_state['replay_paused'] = True

def parse_serial_line(line):
    """Parse the formatted output from your receiver"""
    if app_state['mode'] != 'live':
        return

    try:
        if 'GPS:' in line and 'GPS Spd:' not in line:
            match = re.search(r'GPS:\s*([+-]?[0-9]*\.?[0-9]+),\s*([+-]?[0-9]*\.?[0-9]+)', line)
            if match:
                candidate_lat = float(match.group(1))
                candidate_lon = float(match.group(2))
                if gps_reading_is_plausible(candidate_lat, candidate_lon):
                    latest['lat'] = candidate_lat
                    latest['lon'] = candidate_lon
        elif 'Position:' in line:
            match = re.search(r'Position:\s*([+-]?[0-9]*\.?[0-9]+),\s*([+-]?[0-9]*\.?[0-9]+)', line)
            if match:
                candidate_lat = float(match.group(1))
                candidate_lon = float(match.group(2))
                if gps_reading_is_plausible(candidate_lat, candidate_lon):
                    latest['lat'] = candidate_lat
                    latest['lon'] = candidate_lon
        elif 'GPS Spd:' in line:
            match = re.search(r'GPS Spd:\s*([+-]?[0-9]*\.?[0-9]+)\s*kph\s*\|\s*Alt:\s*([+-]?[0-9]*\.?[0-9]+)\s*m\s*\|\s*Sat:\s*(\d+)\s*\|\s*Fix:\s*(Valid|No Fix)', line)
            if match:
                latest['speed'] = float(match.group(1))
                latest['alt'] = float(match.group(2))
                latest['sats'] = int(match.group(3))
                latest['fix'] = match.group(4) == 'Valid'
        elif 'Speed:' in line and 'GPS Spd:' not in line:
            latest['speed'] = float(line.split('Speed:')[1].strip().split()[0])
        elif 'Altitude:' in line and 'GPS Spd:' not in line:
            latest['alt'] = float(line.split('Altitude:')[1].strip().split()[0])
        elif 'Satellites:' in line:
            latest['sats'] = int(line.split('Satellites:')[1].strip().split()[0])
        elif 'GPS Fix:' in line:
            latest['fix'] = 'Valid' in line
        elif 'RPM:' in line and 'TPS:' in line:
            match = re.search(r'RPM:\s*(\d+)\s*\|\s*TPS:\s*([+-]?[0-9]*\.?[0-9]+)%\s*\|\s*Eng:\s*([+-]?[0-9]*\.?[0-9]+)\s*C\s*\|\s*Oil:\s*([+-]?[0-9]*\.?[0-9]+)\s*Bar', line)
            if match:
                latest['rpm'] = int(match.group(1))
                latest['tps'] = float(match.group(2))
                latest['engine_temp'] = float(match.group(3))
                latest['oil_pressure'] = float(match.group(4))
        elif 'Fuel:' in line and 'Brake:' in line:
            match = re.search(r'Fuel:\s*([+-]?[0-9]*\.?[0-9]+)\s*Bar\s*\|\s*Brake:\s*([+-]?[0-9]*\.?[0-9]+)\s*Bar\s*\|\s*(?:Volt|Voltage):\s*([+-]?[0-9]*\.?[0-9]+)\s*V', line)
            if match:
                latest['fuel_pressure'] = float(match.group(1))
                latest['brake_pressure'] = float(match.group(2))
                latest['battery_voltage'] = float(match.group(3))
        elif 'Wheels FR/FL/RR/RL:' in line:
            match = re.search(r'Wheels FR/FL/RR/RL:\s*(\d+)/(\d+)/(\d+)/(\d+)', line)
            if match:
                latest['wheel_speed_fr'] = int(match.group(1))
                latest['wheel_speed_fl'] = int(match.group(2))
                latest['wheel_speed_rr'] = int(match.group(3))
                latest['wheel_speed_rl'] = int(match.group(4))
        elif 'Lateral G:' in line and 'Heading:' in line:
            match = re.search(r'Lateral G:\s*([+-]?[0-9]*\.?[0-9]+)\s*\|\s*Heading:\s*([+-]?[0-9]*\.?[0-9]+)\s*deg', line)
            if match:
                latest['g_force_lateral'] = float(match.group(1))
                latest['heading'] = float(match.group(2))
        elif 'TX Count:' in line and 'CAN Frames:' in line:
            match = re.search(r'TX Count:\s*(\d+)\s*\|\s*CAN Frames:\s*(\d+)', line)
            if match:
                latest['tx_count'] = int(match.group(1))
                latest['can_frame_count'] = int(match.group(2))
        elif 'RSSI:' in line and 'SNR:' in line:
            parts = line.split('|')
            latest['rssi'] = int(parts[0].split('RSSI:')[1].strip().split()[0])
            latest['snr'] = int(parts[1].split('SNR:')[1].strip().split()[0])
            store_datapoint()
    except Exception as e:
        pass

def store_datapoint():
    sample = snapshot_latest()
    apply_sample(sample, count_rx_total=True, append_to_buffer=True)
    serial_status['last_packet_at'] = time.monotonic()
    serial_status['last_packet_received_at'] = datetime.now()
    write_recording_row(sample)

def find_serial_port():
    """Find available Pico serial port"""
    for port in SERIAL_PORTS:
        if os.path.exists(port):
            return port
    ports = glob.glob('/dev/ttyACM*')
    return ports[0] if ports else None

def serial_reader():
    """Background thread to read serial data - simplified like minicom"""
    while True:
        port = find_serial_port()
        if not port:
            print("No serial port found, waiting...")
            serial_status['connected'] = False
            time.sleep(2)
            continue
        
        ser = None
        try:
            # Simple open like minicom does - no fancy locking
            ser = serial.Serial(
                port=port,
                baudrate=BAUD_RATE,
                timeout=0.1,        # Short timeout, non-blocking style
                exclusive=True,     # Prevent other processes (Python 3.6+)
            )
            
            serial_status['connected'] = True
            serial_status['port'] = port
            print(f"Connected to {port}")
            
            # Clear any garbage
            ser.reset_input_buffer()
            
            buffer = ""
            while True:
                try:
                    # Read available bytes (non-blocking style)
                    if ser.in_waiting:
                        chunk = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                        buffer += chunk
                        
                        # Process complete lines
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            if line.strip():
                                parse_serial_line(line)
                    else:
                        time.sleep(0.01)  # 10ms idle sleep
                        
                except OSError as e:
                    print(f"Read error: {e}")
                    break
                    
        except serial.SerialException as e:
            print(f"Serial error: {e}")
        except Exception as e:
            print(f"Error: {e}")
        finally:
            serial_status['connected'] = False
            if ser and ser.is_open:
                ser.close()
            time.sleep(1)

# Start serial reader thread
threading.Thread(target=serial_reader, daemon=True).start()


def control_text():
    if app_state['mode'] == 'replay' and app_state['replay_rows']:
        total = len(app_state['replay_rows'])
        position = min(app_state['replay_index'], total)
        state = 'Paused' if app_state['replay_paused'] else 'Playing'
        return f"Replay {state} {position}/{total} at {app_state['replay_speed']}x"

    if app_state['recording']:
        return f"Recording to {app_state['recording_path']}"

    return 'Live telemetry'


def set_live_mode():
    app_state['mode'] = 'live'
    app_state['replay_paused'] = True
    app_state['replay_index'] = 0
    app_state['replay_rows'] = []
    app_state['replay_filename'] = None
    reset_telemetry_buffers()


def start_recording():
    app_state['recording_path'] = make_recording_path()
    app_state['recording'] = True


def stop_recording():
    app_state['recording'] = False
    app_state['recording_path'] = None


def start_replay(rows, filename=None):
    stop_recording()
    app_state['mode'] = 'replay'
    app_state['replay_rows'] = rows
    app_state['replay_index'] = 0
    app_state['replay_paused'] = True
    app_state['replay_speed'] = 1
    app_state['replay_filename'] = filename
    reset_telemetry_buffers()
    if rows:
        apply_sample(rows[0], count_rx_total=False, append_to_buffer=True)
        app_state['replay_index'] = 1


def reset_replay_to_start():
    if app_state['mode'] != 'replay':
        return

    app_state['replay_paused'] = True
    app_state['replay_index'] = 0
    reset_telemetry_buffers()
    if app_state['replay_rows']:
        apply_sample(app_state['replay_rows'][0], count_rx_total=False, append_to_buffer=True)
        app_state['replay_index'] = 1

# Dash App
app = dash.Dash(__name__, update_title=None)
app.title = "FS26 Telemetry Dashboard"

page_style = {
    'backgroundColor': '#0f1320',
    'minHeight': '100vh',
    'fontFamily': '"Segoe UI", "Inter", sans-serif',
    'color': '#f5f7fb',
}

header_style = {
    'background': 'linear-gradient(180deg, #171d2d 0%, #121726 100%)',
    'padding': '1.25rem 1.5rem',
    'borderBottom': '1px solid #273043',
}

grid_style = {
    'display': 'grid',
    'gridTemplateColumns': 'repeat(auto-fit, minmax(250px, 1fr))',
    'gap': '1rem',
    'padding': '1rem 1rem 0 1rem',
}

control_button_style = {
    'display': 'inline-flex',
    'alignItems': 'center',
    'justifyContent': 'center',
    'padding': '0.55rem 0.9rem',
    'border': '1px solid #273043',
    'borderRadius': '8px',
    'backgroundColor': '#1a2130',
    'color': '#f5f7fb',
    'cursor': 'pointer',
    'fontSize': '0.95rem',
}

app.layout = html.Div([
    html.Div([
        html.H1("FS26 Telemetry Dashboard", style={'margin': '0', 'fontSize': '1.8rem'}),
        html.Div("Combined GPS, CAN, and radio link status in one view.", style={'color': '#aab3c5', 'marginTop': '0.35rem'}),
    ], style=header_style),

    html.Div(id='status-display', style={
        'padding': '0.75rem 1rem 0 1rem',
        'color': '#d7dce7',
        'fontSize': '0.95rem',
    }),

    html.Div([
        html.Div(id='connection-card'),
        html.Div(id='gps-card'),
        html.Div(id='engine-card'),
        html.Div(id='pressure-card'),
        html.Div(id='wheel-card'),
        html.Div(id='dynamics-card'),
    ], style=grid_style),

    html.Div([
        html.Div(id='replay-status', style={'color': '#aab3c5', 'fontSize': '0.95rem'}),
        html.Div([
            html.Button('Record to CSV', id='record-toggle', n_clicks=0, style=control_button_style),
            html.Button('Play', id='play-toggle', n_clicks=0, style=control_button_style),
            html.Button('Pause', id='pause-toggle', n_clicks=0, style=control_button_style),
            html.Button('Fast-forward', id='ff-toggle', n_clicks=0, style=control_button_style),
            html.Button('1x', id='reset-speed-toggle', n_clicks=0, style=control_button_style),
            html.Button('Live', id='live-toggle', n_clicks=0, style=control_button_style),
            dcc.Upload(
                id='replay-upload',
                children=html.Div('Load CSV'),
                accept='.csv',
                multiple=False,
                style={
                    **control_button_style,
                },
            ),
            html.Span('Speed: 1x', id='speed-display', style={'color': '#8a93a6'}),
        ], style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '0.75rem', 'alignItems': 'center'}),
    ], style={'padding': '0.75rem 1rem 0 1rem', 'display': 'grid', 'gap': '0.5rem'}),

    html.Div([
        dcc.Graph(id='map-graph', style={'height': '52vh'}),
    ], style={'padding': '1rem'}),

    html.Div([
        dcc.Graph(id='speed-graph', style={'height': '26vh', 'width': '50%', 'display': 'inline-block'}),
        dcc.Graph(id='signal-graph', style={'height': '26vh', 'width': '50%', 'display': 'inline-block'}),
    ], style={'padding': '0 1rem 1rem 1rem'}),

    dcc.Interval(id='interval-component', interval=250, n_intervals=0),
], style=page_style)

@app.callback(
    [Output('status-display', 'children'),
     Output('connection-card', 'children'),
     Output('gps-card', 'children'),
     Output('engine-card', 'children'),
     Output('pressure-card', 'children'),
     Output('wheel-card', 'children'),
     Output('dynamics-card', 'children'),
     Output('map-graph', 'figure'),
     Output('speed-graph', 'figure'),
     Output('signal-graph', 'figure')],
    [Input('interval-component', 'n_intervals')]
)
def update_dashboard(n):
    replay_step()

    # Connection status
    if serial_status['connected']:
        age = time.monotonic() - serial_status['last_packet_at'] if serial_status['last_packet_at'] else 999
        if age < 5:
            status = html.Span(
                [f"Connected to {serial_status['port']} ", html.Span(f"RX packets: {latest['rx_total']}", style={'color': '#8a93a6'}), html.Span(f" | {control_text()}", style={'color': '#aab3c5'})],
                style={'color': '#7ce38b'}
            )
        else:
            status = html.Span([f"Connected to {serial_status['port']} but no fresh data ", html.Span(control_text(), style={'color': '#aab3c5'})], style={'color': '#f2c14e'})
    else:
        status = html.Span(["Disconnected ", html.Span(control_text(), style={'color': '#aab3c5'})], style={'color': '#ff7a7a'})

    connection_card = section_card('Connection', [
        stat_row('State', 'Connected' if serial_status['connected'] else 'Disconnected'),
        stat_row('Port', serial_status['port'] or '--'),
        stat_row('Packet received at', serial_status['last_packet_received_at'].strftime('%H:%M:%S') if serial_status['last_packet_received_at'] else '--'),
        stat_row('RX packets', fmt_int(latest['rx_total'])),
        stat_row('Buffered samples', fmt_int(latest['rx_count'])),
    ])

    gps_card = section_card('GPS', [
        stat_row('Latitude', fmt_float(latest['lat'], 6)),
        stat_row('Longitude', fmt_float(latest['lon'], 6)),
        stat_row('Speed', fmt_float(latest['speed'], 1, ' kph')),
        stat_row('Altitude', fmt_float(latest['alt'], 1, ' m')),
        stat_row('Satellites', fmt_int(latest['sats'])),
        stat_row('Fix', fmt_bool(latest['fix'])),
    ])

    engine_card = section_card('Engine and drivetrain', [
        stat_row('RPM', fmt_int(latest['rpm'])),
        stat_row('Engine temp', fmt_float(latest['engine_temp'], 1, ' C')),
        stat_row('Throttle position', fmt_float(latest['tps'], 1, ' %')),
        stat_row('Battery voltage', fmt_float(latest['battery_voltage'], 2, ' V')),
    ])

    pressure_card = section_card('Pressures', [
        stat_row('Oil pressure', fmt_float(latest['oil_pressure'], 2, ' bar')),
        stat_row('Fuel pressure', fmt_float(latest['fuel_pressure'], 2, ' bar')),
        stat_row('Brake pressure', fmt_float(latest['brake_pressure'], 2, ' bar')),
    ])

    wheel_card = section_card('Wheel speeds', [
        stat_row('Front right', fmt_int(latest['wheel_speed_fr'], ' km/h')),
        stat_row('Front left', fmt_int(latest['wheel_speed_fl'], ' km/h')),
        stat_row('Rear right', fmt_int(latest['wheel_speed_rr'], ' km/h')),
        stat_row('Rear left', fmt_int(latest['wheel_speed_rl'], ' km/h')),
    ])

    dynamics_card = section_card('Dynamics and radio', [
        stat_row('Lateral G', fmt_float(latest['g_force_lateral'], 2)),
        stat_row('Heading', fmt_float(latest['heading'], 1, ' deg')),
        stat_row('TX count', fmt_int(latest['tx_count'])),
        stat_row('CAN frames', fmt_int(latest['can_frame_count'])),
        stat_row('RSSI', fmt_int(latest['rssi'], ' dBm')),
        stat_row('SNR', fmt_int(latest['snr'], ' dB')),
    ])
    
    # Map - using Scattermap (not deprecated Scattermapbox)
    lat_list = list(telemetry_data['latitude'])
    lon_list = list(telemetry_data['longitude'])
    
    map_fig = go.Figure()
    
    if lat_list and lon_list:
        # Trail
        map_fig.add_trace(go.Scattermap(
            lat=lat_list,
            lon=lon_list,
            mode='lines+markers',
            marker=dict(size=6, color='#00d4ff'),
            line=dict(width=3, color='#00d4ff'),
            name='Track',
        ))
        # Current position (larger marker)
        map_fig.add_trace(go.Scattermap(
            lat=[lat_list[-1]],
            lon=[lon_list[-1]],
            mode='markers',
            marker=dict(size=15, color='#00ff88'),
            name='Current',
        ))
        center_lat, center_lon = lat_list[-1], lon_list[-1]
    else:
        center_lat, center_lon = 0, 0
    
    map_fig.update_layout(
        map=dict(
            style='carto-darkmatter',
            zoom=15,
            center=dict(lat=center_lat, lon=center_lon),
        ),
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor='#0f0f23',
        showlegend=False,
        uirevision='constant',
    )
    
    # Speed graph
    speed_fig = go.Figure(go.Scatter(
        y=list(telemetry_data['speed_kph']),
        mode='lines',
        fill='tozeroy',
        line=dict(color='#00ff88', width=2),
        fillcolor='rgba(0,255,136,0.2)',
    ))
    speed_fig.update_layout(
        title=None,
        template='plotly_dark',
        paper_bgcolor='#0f0f23',
        plot_bgcolor='#16213e',
        yaxis_title='Speed (kph)',
        margin=dict(l=50, r=20, t=20, b=30),
        uirevision='constant',
    )
    
    # Signal graph
    signal_fig = go.Figure()
    signal_fig.add_trace(go.Scatter(y=list(telemetry_data['rssi']), name='RSSI', line=dict(color='#ff6b6b', width=2)))
    signal_fig.add_trace(go.Scatter(y=list(telemetry_data['snr']), name='SNR', line=dict(color='#aa88ff', width=2)))
    signal_fig.update_layout(
        title=None,
        template='plotly_dark',
        paper_bgcolor='#0f0f23',
        plot_bgcolor='#16213e',
        margin=dict(l=50, r=20, t=20, b=30),
        legend=dict(orientation='h', yanchor='top', y=1.1, x=0.5, xanchor='center'),
        uirevision='constant',
    )
    
    return status, connection_card, gps_card, engine_card, pressure_card, wheel_card, dynamics_card, map_fig, speed_fig, signal_fig


@app.callback(
    [Output('record-toggle', 'children'),
     Output('play-toggle', 'children'),
     Output('pause-toggle', 'children'),
     Output('speed-display', 'children'),
     Output('replay-status', 'children')],
    [Input('record-toggle', 'n_clicks'),
     Input('play-toggle', 'n_clicks'),
     Input('pause-toggle', 'n_clicks'),
     Input('ff-toggle', 'n_clicks'),
     Input('reset-speed-toggle', 'n_clicks'),
     Input('live-toggle', 'n_clicks'),
     Input('replay-upload', 'contents')],
    [State('replay-upload', 'filename')],
    prevent_initial_call=True
)
def handle_controls(record_clicks, play_clicks, pause_clicks, ff_clicks, reset_speed_clicks, live_clicks, upload_contents, upload_filename):
    triggered = dash.callback_context.triggered[0]['prop_id'].split('.')[0]

    if triggered == 'record-toggle':
        if app_state['recording']:
            stop_recording()
        else:
            start_recording()
    elif triggered == 'play-toggle':
        if app_state['mode'] == 'replay' and app_state['replay_rows']:
            if not app_state['replay_paused']:
                reset_replay_to_start()
            else:
                app_state['replay_paused'] = False
    elif triggered == 'pause-toggle':
        if app_state['mode'] == 'replay' and app_state['replay_rows']:
            app_state['replay_paused'] = not app_state['replay_paused']
    elif triggered == 'ff-toggle':
        if app_state['mode'] == 'replay' and app_state['replay_rows']:
            app_state['replay_speed'] = min(app_state['replay_speed'] * 2, 16)
    elif triggered == 'reset-speed-toggle':
        if app_state['mode'] == 'replay' and app_state['replay_rows']:
            app_state['replay_speed'] = 1
    elif triggered == 'live-toggle':
        set_live_mode()
    elif triggered == 'replay-upload' and upload_contents:
        rows = load_replay_csv(upload_contents)
        start_replay(rows, upload_filename)

    record_text = 'Stop recording' if app_state['recording'] else 'Record to CSV'
    play_text = 'Stop/Reset' if (app_state['mode'] == 'replay' and app_state['replay_rows'] and not app_state['replay_paused']) else 'Play'
    pause_text = 'Resume' if (app_state['mode'] == 'replay' and app_state['replay_paused']) else 'Pause'
    speed_text = f"Speed: {app_state['replay_speed']}x"
    replay_text = control_text() if app_state['mode'] == 'replay' else 'No replay loaded'

    return record_text, play_text, pause_text, speed_text, replay_text

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=8050)  # debug=False for production