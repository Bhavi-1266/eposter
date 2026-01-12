#!/usr/bin/env python3
import json
import os
import socket
import threading
from pathlib import Path
from flask import Flask, request, redirect, render_template_string
from dnslib import DNSRecord, QTYPE, A, RR

# --- Config ---
PROJECT_DIR = Path("/home/bhavy/Projects/eposter")
CONFIG_FILE = PROJECT_DIR / 'config.json'
PORT = 80

app = Flask(__name__)

# --- HTML Template ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>ePoster Admin</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: sans-serif; background: #222; color: #fff; padding: 20px; }
        .container { max-width: 500px; margin: 0 auto; background: #333; padding: 20px; border-radius: 8px; }
        h2 { text-align: center; color: #00d4ff; margin-top: 0; }
        .status-bar { background: #444; padding: 10px; margin-bottom: 20px; border-left: 4px solid #00d4ff; }
        label { display: block; margin-top: 15px; font-size: 0.9em; color: #aaa; }
        input { width: 100%; padding: 10px; margin-top: 5px; background: #222; border: 1px solid #555; color: #fff; border-radius: 4px; box-sizing: border-box; }
        .section-title { margin-top: 25px; border-bottom: 1px solid #555; padding-bottom: 5px; color: #fff; font-weight: bold; }
        button { background: #00d4ff; color: #000; width: 100%; padding: 12px; border: none; font-weight: bold; margin-top: 25px; cursor: pointer; border-radius: 4px; font-size: 16px; }
        button:hover { background: #00b7db; }
    </style>
</head>
<body>
    <div class="container">
        <h2>ePoster Manager</h2>
        
        <div class="status-bar">
            <strong>Current Status</strong><br>
            Connected to: {{ hostname }}<br>
            Device ID: {{ config.ID }}
        </div>

        <form action="/save" method="post">
            <div class="section-title">Identity</div>
            <label>Unit ID</label>
            <input type="number" name="unit_id" value="{{ config.ID }}">

            <div class="section-title">Wi-Fi Settings</div>
            <label>Primary SSID</label>
            <input type="text" name="ssid1" value="{{ config.wifi.ssid1 }}">
            <label>Primary Password</label>
            <input type="text" name="pass1" value="{{ config.wifi.password1 }}">
            
            <label>Backup SSID</label>
            <input type="text" name="ssid2" value="{{ config.wifi.ssid2 }}">
            <label>Backup Password</label>
            <input type="text" name="pass2" value="{{ config.wifi.password2 }}">

            <div class="section-title">Display Config</div>
            <label>Content ID (Screen Number)</label>
            <input type="number" name="device_id" value="{{ config.display.device_id }}">
            <label>Rotation</label>
            <input type="number" name="rotation" value="{{ config.display.rotation_degree }}">

            <button type="submit">Save Changes</button>
        </form>
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

# --- DNS Server (Only runs if port 53 is available) ---
def dns_server(ip_address):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((ip_address, 53))
        print(f"[*] DNS Captive Portal Active on {ip_address}")
    except OSError:
        # Port 53 busy usually means systemd-resolved is running (Normal WiFi Mode)
        # We fail silently here so the web server still runs.
        return

    while True:
        data, addr = sock.recvfrom(512)
        try:
            request = DNSRecord.parse(data)
            reply = DNSRecord(DNSRecord.header(request.id, qr=1, aa=1, ra=1), q=request.q)
            qname = request.q.qname
            qtype = request.q.qtype
            if qtype == QTYPE.A:
                reply.add_answer(RR(qname, qtype, rdata=A(ip_address), ttl=60))
                sock.sendto(reply.pack(), addr)
        except Exception:
            pass

# --- Web Routes ---
def load_config():
    if not CONFIG_FILE.exists(): return {"ID": 0, "wifi": {}, "display": {}}
    with open(CONFIG_FILE, 'r') as f: return json.load(f)

@app.route('/')
def home():
    current_hostname = socket.gethostname()
    return render_template_string(HTML_TEMPLATE, config=load_config(), hostname=current_hostname)

@app.route('/save', methods=['POST'])
def save():
    conf = load_config()
    
    try:
        # 1. Update Config Object
        conf['ID'] = int(request.form.get('unit_id'))
        conf['wifi']['ssid1'] = request.form.get('ssid1')
        conf['wifi']['password1'] = request.form.get('pass1')
        conf['wifi']['ssid2'] = request.form.get('ssid2')
        conf['wifi']['password2'] = request.form.get('pass2')
        conf['display']['device_id'] = int(request.form.get('device_id'))
        conf['display']['rotation_degree'] = int(request.form.get('rotation'))
        
        # 2. Save to File
        with open(CONFIG_FILE, 'w') as f:
            json.dump(conf, f, indent=2)

        # 3. Return Success Page (No Hostname change, No Reboot)
        return """
        <html>
        <body style="font-family: sans-serif; background: #222; color: #fff; text-align: center; padding: 50px;">
            <h1 style="color: #00d4ff;">Settings Saved!</h1>
            <p>The configuration has been updated successfully.</p>
            <br>
            <button onclick="window.location.href='/'" style="padding: 10px 20px; font-size: 16px; cursor: pointer; background: #444; color: #fff; border: 1px solid #555;">Go Back</button>
        </body>
        </html>
        """
    except Exception as e:
        return f"<h1>Error Saving</h1><p>{e}</p>"

# Captive Portal Checks
@app.route('/generate_204')
@app.route('/ncsi.txt')
def captive_check(): return redirect('/', code=302)

if __name__ == '__main__':
    # 1. Determine IP
    current_ip = get_ip()
    print(f"[*] Web Admin running on: http://{current_ip}")

    # 2. Try to start DNS (Will fail silently if on normal WiFi)
    t = threading.Thread(target=dns_server, args=(current_ip,), daemon=True)
    t.start()
    
    # 3. Start Web Server
    app.run(host='0.0.0.0', port=PORT, debug=False)