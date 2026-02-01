#!/usr/bin/env python3
import json
import os
import socket
import threading
from pathlib import Path
from flask import Flask, request, redirect, render_template_string
from dnslib import DNSRecord, QTYPE, A, RR
from dnslib.server import DNSServer, DNSHandler, BaseResolver

# --- Config ---
PROJECT_DIR = Path(__file__).parent
CONFIG_FILE = PROJECT_DIR / 'config.json'
PORT = 80

app = Flask(__name__)

# --- HTML Template ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ePoster Manager</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 20px; }
        .container { max-width: 600px; margin: 0 auto; background: white; border-radius: 10px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); overflow: hidden; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; }
        .header h1 { font-size: 28px; margin-bottom: 10px; }
        .status { background: rgba(255,255,255,0.2); padding: 10px; border-radius: 5px; margin-top: 15px; font-size: 14px; }
        .content { padding: 30px; }
        .section { margin-bottom: 30px; }
        .section h2 { color: #667eea; margin-bottom: 15px; font-size: 18px; border-bottom: 2px solid #667eea; padding-bottom: 5px; }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; color: #333; font-weight: bold; font-size: 14px; }
        input, select { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px; font-size: 14px; }
        input:focus, select:focus { outline: none; border-color: #667eea; }
        input[readonly] { background: #f5f5f5; cursor: not-allowed; }
        .btn { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; padding: 12px 30px; border-radius: 5px; cursor: pointer; font-size: 16px; width: 100%; margin-top: 20px; }
        .btn:hover { opacity: 0.9; }
        .error { background: #fee; color: #c33; padding: 10px; border-radius: 5px; margin-bottom: 15px; border-left: 4px solid #c33; }
        .note { font-size: 12px; color: #666; margin-top: 5px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>ePoster Manager</h1>
            <div class="status">
                <strong>Current Status</strong><br>
                Connected to: {{ hostname }}<br>
                Device ID: {{ config.ID }}
            </div>
        </div>
        <div class="content">
            {% if error %}
            <div class="error">{{ error }}</div>
            {% endif %}
            <form method="POST" action="/save">
                <div class="section">
                    <h2>Identity</h2>
                    <div class="form-group">
                        <label>Unit ID (Read Only)</label>
                        <input type="number" name="unit_id" value="{{ config.ID }}" readonly>
                    </div>
                </div>

                <div class="section">
                    <h2>Operation Mode</h2>
                    <div class="form-group">
                        <label>Current Mode</label>
                        <select name="mode">
                            <option value="Time" {% if config.display.Mode == "Time" %}selected{% endif %}>Time Schedule</option>
                            <option value="Menu" {% if config.display.Mode == "Menu" %}selected{% endif %}>Menu (Interactive)</option>
                            <option value="Scroll" {% if config.display.Mode == "Scroll" %}selected{% endif %}>Auto Scroll</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Auto Scroll Duration (Seconds)</label>
                        <input type="number" name="auto_scroll" value="{{ config.display.Auto_Scroll }}" min="1">
                    </div>
                </div>

                <div class="section">
                    <h2>Display Config</h2>
                    <div class="form-group">
                        <label>Content ID (Screen Number)</label>
                        <input type="number" name="device_id" value="{{ config.display.device_id }}" min="0">
                    </div>
                    <div class="form-group">
                        <label>Rotation (0, 90, 180, 270)</label>
                        <select name="rotation">
                            <option value="0" {% if config.display.rotation_degree == 0 %}selected{% endif %}>0°</option>
                            <option value="90" {% if config.display.rotation_degree == 90 %}selected{% endif %}>90°</option>
                            <option value="180" {% if config.display.rotation_degree == 180 %}selected{% endif %}>180°</option>
                            <option value="270" {% if config.display.rotation_degree == 270 %}selected{% endif %}>270°</option>
                        </select>
                    </div>
                </div>

                <div class="section">
                    <h2>Wi-Fi Settings</h2>
                    <div class="form-group">
                        <label>Primary SSID</label>
                        <input type="text" name="ssid1" value="{{ config.wifi.ssid1 }}">
                    </div>
                    <div class="form-group">
                        <label>Primary Password</label>
                        <input type="password" name="pass1" value="{{ config.wifi.password1 }}">
                    </div>
                    <div class="form-group">
                        <label>Backup SSID</label>
                        <input type="text" name="ssid2" value="{{ config.wifi.ssid2 }}">
                    </div>
                    <div class="form-group">
                        <label>Backup Password</label>
                        <input type="password" name="pass2" value="{{ config.wifi.password2 }}">
                    </div>
                </div>

                <div class="section">
                    <h2>API Configuration</h2>
                    <div class="form-group">
                        <label>Poster API URL</label>
                        <input type="text" name="poster_api_url" value="{{ config.api.poster_api_url }}">
                    </div>
                </div>

                <div class="section">
                    <h2>Authorization</h2>
                    <div class="form-group">
                        <label>Admin Password (Required to Save)</label>
                        <input type="password" name="admin_password" required>
                        <div class="note">Enter your admin password to save changes</div>
                    </div>
                </div>

                <button type="submit" class="btn">Save Changes</button>
            </form>
        </div>
    </div>
</body>
</html>
"""

# --- Helper: Get IP Address ---
def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

# --- Custom DNS Resolver ---
class CustomResolver(BaseResolver):
    def __init__(self, ip_address, config_file):
        self.ip_address = ip_address
        self.config_file = config_file
    
    def get_device_id(self):
        """Load device ID from config"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    return config.get('ID', 0)
        except Exception:
            pass
        return 0
    
    def resolve(self, request, handler):
        reply = request.reply()
        qname = str(request.q.qname).lower()
        
        # Get current device ID
        device_id = self.get_device_id()
        target_hostname = f"setupeposter{device_id}."
        
        # Check if the query is for our custom hostname or any domain (captive portal)
        if qname.startswith("setupeposter") or True:  # Respond to all DNS queries for captive portal
            if request.q.qtype == QTYPE.A:
                reply.add_answer(
                    RR(
                        request.q.qname,
                        QTYPE.A,
                        rdata=A(self.ip_address),
                        ttl=60
                    )
                )
        
        return reply

# --- DNS Server ---
def start_dns_server(ip_address, config_file):
    """Start DNS server with custom resolver"""
    try:
        resolver = CustomResolver(ip_address, config_file)
        dns_server = DNSServer(
            resolver,
            port=53,
            address=ip_address,
            tcp=False
        )
        print(f"[*] DNS Server Active on {ip_address}:53")
        print(f"[*] Resolving setupEposter[ID] to {ip_address}")
        dns_server.start()
    except Exception as e:
        print(f"[!] DNS Server Error: {e}")

# --- Web Routes ---
def load_config():
    default_config = {
        "ID": 0,
        "password": "admin",  # Default password if none exists
        "wifi": {"ssid1": "", "password1": "", "ssid2": "", "password2": ""},
        "api": {"poster_api_url": ""},
        "display": {
            "device_id": 0,
            "rotation_degree": 0,
            "Mode": "Menu",
            "Auto_Scroll": 5
        }
    }
    
    if not CONFIG_FILE.exists():
        return default_config
    
    try:
        with open(CONFIG_FILE, 'r') as f:
            data = json.load(f)
        # Ensure basic structure exists
        for key in default_config:
            if key not in data:
                data[key] = default_config[key]
        return data
    except Exception:
        return default_config

@app.route('/')
def home():
    error = request.args.get('error')
    conf = load_config()
    current_hostname = f"setupEposter{conf['ID']}"
    return render_template_string(HTML_TEMPLATE, config=conf, hostname=current_hostname, error=error)

@app.route('/save', methods=['POST'])
def save():
    conf = load_config()
    input_password = request.form.get('admin_password')
    
    # Password Verification
    if input_password != conf.get('password'):
        return redirect('/?error=Incorrect+Admin+Password')
    
    try:
        # Update fields
        conf['display']['device_id'] = int(request.form.get('device_id'))
        conf['display']['rotation_degree'] = int(request.form.get('rotation'))
        conf['display']['Mode'] = request.form.get('mode')
        conf['display']['Auto_Scroll'] = int(request.form.get('auto_scroll'))
        
        conf['wifi']['ssid1'] = request.form.get('ssid1')
        conf['wifi']['password1'] = request.form.get('pass1')
        conf['wifi']['ssid2'] = request.form.get('ssid2')
        conf['wifi']['password2'] = request.form.get('pass2')
        
        conf['api']['poster_api_url'] = request.form.get('poster_api_url')
        
        # Save to File
        with open(CONFIG_FILE, 'w') as f:
            json.dump(conf, f, indent=2)
        
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Settings Saved</title>
            <style>
                body { font-family: Arial; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; }
                .box { background: white; padding: 40px; border-radius: 10px; text-align: center; box-shadow: 0 10px 40px rgba(0,0,0,0.2); }
                h1 { color: #667eea; margin-bottom: 20px; }
                .btn { display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; margin-top: 20px; }
            </style>
        </head>
        <body>
            <div class="box">
                <h1>Settings Saved!</h1>
                <p>The configuration has been updated successfully.</p>
                <a href="/" class="btn">Go Back</a>
            </div>
        </body>
        </html>
        """
    except Exception as e:
        return f"<h1>Error Saving</h1><p>{e}</p>"

@app.route('/generate_204')
@app.route('/ncsi.txt')
def captive_check():
    return redirect('/', code=302)

if __name__ == '__main__':
    current_ip = get_ip()
    conf = load_config()
    
    print(f"[*] Device ID: {conf['ID']}")
    print(f"[*] DNS Hostname: setupEposter{conf['ID']}")
    print(f"[*] Web Admin running on: http://{current_ip}")
    print(f"[*] Access via: http://setupEposter{conf['ID']}")
    
    # Start DNS Server in background thread
    dns_thread = threading.Thread(
        target=start_dns_server, 
        args=(current_ip, CONFIG_FILE), 
        daemon=True
    )
    dns_thread.start()
    
    # Start Flask Web Server
    app.run(host='0.0.0.0', port=PORT, debug=False)