#!/usr/bin/env python3
import json
import os
import socket
import time
from pathlib import Path
from flask import Flask, request, redirect, render_template_string, jsonify

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
        
        /* Toast Notification Styles */
        .toast {
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 15px 20px;
            border-radius: 5px;
            color: white;
            font-weight: bold;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            z-index: 1000;
            animation: slideIn 0.3s ease-out;
            display: none;
        }
        .toast.success { background: #4caf50; }
        .toast.error { background: #f44336; }
        .toast.show { display: block; }
        
        @keyframes slideIn {
            from {
                transform: translateX(400px);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }
        
        @keyframes slideOut {
            from {
                transform: translateX(0);
                opacity: 1;
            }
            to {
                transform: translateX(400px);
                opacity: 0;
            }
        }
    </style>
</head>
<body>
    <div id="toast" class="toast"></div>
    
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
            <form method="POST" action="/save" id="configForm">
                <div class="section">
                    <h2>Authorization</h2>
                    <div class="form-group">
                        <label>Admin Password (Required to Save)</label>
                        <input type="password" name="admin_password" id="admin_password" required>
                        <div class="note">Enter your admin password to save changes</div>
                    </div>
                </div>
                
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

                <button type="submit" class="btn">Save Changes</button>
            </form>
        </div>
    </div>
    
    <script>
        const form = document.getElementById('configForm');
        const toast = document.getElementById('toast');
        
        function showToast(message, type) {
            toast.textContent = message;
            toast.className = 'toast ' + type + ' show';
            
            setTimeout(() => {
                toast.style.animation = 'slideOut 0.3s ease-out';
                setTimeout(() => {
                    toast.classList.remove('show');
                    toast.style.animation = '';
                }, 300);
            }, 3000);
        }
        
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const formData = new FormData(form);
            
            try {
                const response = await fetch('/save', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (result.success) {
                    showToast(result.message, 'success');
                    // Clear password field after successful save
                    document.getElementById('admin_password').value = '';
                } else {
                    showToast(result.message, 'error');
                }
            } catch (error) {
                showToast('Error saving settings', 'error');
            }
        });
    </script>
</body>
</html>
"""

# --- Helper: Get IP Address ---
def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't actually connect, just used to find local IP
        s.connect(('8.8.8.8', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

# --- Passive Wi-Fi Check ---
def wait_for_wifi(timeout_interval=5):
    """
    Waits until the device has a valid network IP 
    and can reach the outside world.
    """
    print("[*] Entering Passive Mode: Waiting for Wi-Fi connection...")
    while True:
        ip = get_ip()
        if ip != '127.0.0.1':
            print(f"[*] Wi-Fi Connected! Local IP: {ip}")
            return ip
        else:
            print(f"[-] No connection found. Retrying in {timeout_interval}s...")
            time.sleep(timeout_interval)

# --- Config Management ---
def load_config():
    default_config = {
        "ID": 0,
        "password": "admin",
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
        for key in default_config:
            if key not in data:
                data[key] = default_config[key]
        return data
    except Exception:
        return default_config

# --- Web Routes ---
@app.route('/')
def home():
    conf = load_config()
    return render_template_string(HTML_TEMPLATE, config=conf, hostname=f"ePoster-{conf['ID']}")

@app.route('/save', methods=['POST'])
def save():
    conf = load_config()
    input_password = request.form.get('admin_password')
    
    if input_password != conf.get('password'):
        return jsonify({'success': False, 'message': 'Incorrect Admin Password'})
    
    try:
        # Update configuration
        conf['display']['device_id'] = int(request.form.get('device_id'))
        conf['display']['rotation_degree'] = int(request.form.get('rotation'))
        conf['display']['Mode'] = request.form.get('mode')
        conf['display']['Auto_Scroll'] = int(request.form.get('auto_scroll'))
        conf['wifi']['ssid1'] = request.form.get('ssid1')
        conf['wifi']['password1'] = request.form.get('pass1')
        conf['wifi']['ssid2'] = request.form.get('ssid2')
        conf['wifi']['password2'] = request.form.get('pass2')
        conf['api']['poster_api_url'] = request.form.get('poster_api_url')
        
        with open(CONFIG_FILE, 'w') as f:
            json.dump(conf, f, indent=2)
        
        return jsonify({'success': True, 'message': 'Settings saved successfully!'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error saving settings: {str(e)}'})

# --- Main Entry ---
if __name__ == '__main__':
    # 1. Wait for Wi-Fi (Passive Mode)
    current_ip = wait_for_wifi()
    
    # 2. Load Config
    conf = load_config()
    
    print(f"[*] Starting Web Admin on http://{current_ip}:{PORT}")
    
    # 3. Start Flask (DNS logic removed)
    app.run(host='0.0.0.0', port=PORT, debug=False)