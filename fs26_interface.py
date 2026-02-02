import serial
import dash
from dash import dcc, html
from dash.dependencies import Input, Output
import plotly.graph_objs as go
import threading
from collections import deque
import time
import glob
import os

# Serial config
SERIAL_PORTS = ['/dev/ttyACM1']
BAUD_RATE = 115200

# Data storage (thread-safe with deque)
MAX_POINTS = 500
telemetry_data = {
    'latitude': deque(maxlen=MAX_POINTS),
    'longitude': deque(maxlen=MAX_POINTS),
    'speed_kph': deque(maxlen=MAX_POINTS),
    'altitude': deque(maxlen=MAX_POINTS),
    'satellites': deque(maxlen=MAX_POINTS),
    'rssi': deque(maxlen=MAX_POINTS),
    'snr': deque(maxlen=MAX_POINTS),
    'timestamps': deque(maxlen=MAX_POINTS),
}
latest = {'lat': 0, 'lon': 0, 'speed': 0, 'alt': 0, 'sats': 0, 'fix': False, 'rssi': 0, 'snr': 0, 'tx_count': 0, 'rx_count': 0}
serial_status = {'connected': False, 'port': None, 'last_data': 0}

def parse_serial_line(line):
    """Parse the formatted output from your receiver"""
    try:
        if 'Position:' in line:
            parts = line.split('Position:')[1].strip().split(',')
            latest['lat'] = float(parts[0].strip())
            latest['lon'] = float(parts[1].strip().split()[0])
        elif 'Speed:' in line:
            latest['speed'] = float(line.split('Speed:')[1].strip().split()[0])
        elif 'Altitude:' in line:
            latest['alt'] = float(line.split('Altitude:')[1].strip().split()[0])
        elif 'Satellites:' in line:
            latest['sats'] = int(line.split('Satellites:')[1].strip().split()[0])
        elif 'GPS Fix:' in line:
            latest['fix'] = 'Valid' in line
        elif 'TX Count:' in line:
            latest['tx_count'] = int(line.split('TX Count:')[1].strip().split()[0])
        elif 'RSSI:' in line:
            parts = line.split('|')
            latest['rssi'] = int(parts[0].split('RSSI:')[1].strip().split()[0])
            latest['snr'] = int(parts[1].split('SNR:')[1].strip().split()[0])
            serial_status['last_data'] = time.time()
            store_datapoint()
    except Exception as e:
        pass

def store_datapoint():
    telemetry_data['latitude'].append(latest['lat'])
    telemetry_data['longitude'].append(latest['lon'])
    telemetry_data['speed_kph'].append(latest['speed'])
    telemetry_data['altitude'].append(latest['alt'])
    telemetry_data['satellites'].append(latest['sats'])
    telemetry_data['rssi'].append(latest['rssi'])
    telemetry_data['snr'].append(latest['snr'])
    telemetry_data['timestamps'].append(time.time())
    latest['rx_count'] = len(telemetry_data['timestamps'])

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

# Dash App
app = dash.Dash(__name__)
app.title = "FS26 Telemetry Dashboard"

# Compact stat card style
stat_card_style = {
    'textAlign': 'center',
    'padding': '8px 15px',
    'backgroundColor': '#1a1a2e',
    'borderRadius': '8px',
    'minWidth': '120px',
}

app.layout = html.Div([
    # Header - more compact
    html.Div([
        html.H2("🏎️ FS26 GPS Telemetry", style={'textAlign': 'center', 'color': '#00d4ff', 'margin': '0'}),
    ], style={'backgroundColor': '#1a1a2e', 'padding': '10px'}),
    
    # Live stats cards - COMPACT
    html.Div([
        html.Div([
            html.Span("Speed: ", style={'color': '#888', 'fontSize': '14px'}),
            html.Span(id='speed-display', style={'color': '#00ff88', 'fontSize': '24px', 'fontWeight': 'bold'}),
        ], style=stat_card_style),
        html.Div([
            html.Span("Alt: ", style={'color': '#888', 'fontSize': '14px'}),
            html.Span(id='altitude-display', style={'color': '#ffaa00', 'fontSize': '24px', 'fontWeight': 'bold'}),
        ], style=stat_card_style),
        html.Div([
            html.Span("Sats: ", style={'color': '#888', 'fontSize': '14px'}),
            html.Span(id='sats-display', style={'color': '#00d4ff', 'fontSize': '24px', 'fontWeight': 'bold'}),
        ], style=stat_card_style),
        html.Div([
            html.Span("RSSI: ", style={'color': '#888', 'fontSize': '14px'}),
            html.Span(id='rssi-display', style={'color': '#ff6b6b', 'fontSize': '24px', 'fontWeight': 'bold'}),
        ], style=stat_card_style),
        html.Div([
            html.Span("SNR: ", style={'color': '#888', 'fontSize': '14px'}),
            html.Span(id='snr-display', style={'color': '#aa88ff', 'fontSize': '24px', 'fontWeight': 'bold'}),
        ], style=stat_card_style),
        html.Div(id='status-display', style={**stat_card_style, 'fontSize': '12px'}),
    ], style={'display': 'flex', 'justifyContent': 'center', 'gap': '10px', 'padding': '10px', 'backgroundColor': '#16213e', 'flexWrap': 'wrap'}),
    
    # MAP - now much taller
    html.Div([
        dcc.Graph(id='map-graph', style={'height': '55vh'}),  # More height for map
    ], style={'padding': '10px', 'backgroundColor': '#0f0f23'}),
    
    # Graphs side by side
    html.Div([
        dcc.Graph(id='speed-graph', style={'height': '25vh', 'width': '50%', 'display': 'inline-block'}),
        dcc.Graph(id='signal-graph', style={'height': '25vh', 'width': '50%', 'display': 'inline-block'}),
    ], style={'padding': '0 10px 10px 10px', 'backgroundColor': '#0f0f23'}),
    
    # Auto-refresh
    dcc.Interval(id='interval-component', interval=500, n_intervals=0),
], style={'backgroundColor': '#0f0f23', 'minHeight': '100vh', 'fontFamily': 'monospace'})

@app.callback(
    [Output('speed-display', 'children'),
     Output('altitude-display', 'children'),
     Output('sats-display', 'children'),
     Output('rssi-display', 'children'),
     Output('snr-display', 'children'),
     Output('status-display', 'children'),
     Output('map-graph', 'figure'),
     Output('speed-graph', 'figure'),
     Output('signal-graph', 'figure')],
    [Input('interval-component', 'n_intervals')]
)
def update_dashboard(n):
    # Stats
    speed_text = f"{latest['speed']:.1f} kph"
    alt_text = f"{latest['alt']:.1f} m"
    sats_text = f"{latest['sats']} 🛰️"
    rssi_text = f"{latest['rssi']} dBm"
    snr_text = f"{latest['snr']} dB"
    
    # Connection status
    if serial_status['connected']:
        age = time.time() - serial_status['last_data'] if serial_status['last_data'] else 999
        if age < 5:
            status = html.Span([f"● {serial_status['port']} ", html.Span(f"RX:{latest['rx_count']}", style={'color': '#888'})], style={'color': '#00ff88'})
        else:
            status = html.Span(f"● {serial_status['port']} (no data)", style={'color': '#ffaa00'})
    else:
        status = html.Span("● Disconnected", style={'color': '#ff6b6b'})
    
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
    
    return speed_text, alt_text, sats_text, rssi_text, snr_text, status, map_fig, speed_fig, signal_fig

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=8050)  # debug=False for production