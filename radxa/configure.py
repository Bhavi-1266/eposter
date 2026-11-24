#!/usr/bin/env python3
"""On-demand staff UI. Uses the running receiver's UART owner; never opens a second reader."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Thread

from channel_control import configure_request
from configuration_model import HOST, MODES, decode_record, decode_nodes, encode_record, validate, selection

BASE = Path(__file__).resolve().parent
KEY_FILE = BASE / 'private' / 'encryption_key.txt'
STATIONS = BASE / 'stations.json'


def agent(request):
    # Only a small RPC whitelist is exposed over SSH. Credentials travel on stdin,
    # never in the command line or logs. Replies contain public settings only.
    op = request.get('op')
    if op in ('GET', 'PEER', 'BRIDGE', 'END', 'SCAN'):
        data = b''
    elif op in ('PAIR', 'SPARE'):
        data = bytes.fromhex(request.get('record', ''))
        settings = decode_record(data)
        if len(data) != 120 or (op == 'PAIR' and settings['role'] != 'receiver'):
            raise ValueError('Invalid settings payload')
        if op == 'SPARE':
            slot = request.get('slot')
            if type(slot) is not int or not 0 <= slot < 6:
                raise ValueError('Select a discovered spare')
            # Re-check the selected physical identity immediately before writing.
            status, found = configure_request('SCAN')
            candidates = decode_nodes(found) if status == 'OK' else []
            if not any(n['slot'] == slot and n['unit'] == request.get('unit') and
                       n['nonce'] == request.get('nonce') for n in candidates):
                raise ValueError('Selected spare disappeared or restarted. Scan and select it again.')
            data = selection(request) + data
    elif op == 'IDENTIFY':
        slot = request.get('slot')
        if type(slot) is not int or not 0 <= slot < 6:
            raise ValueError('Select a spare')
        data = selection(request)
    else:
        raise ValueError('Unknown configuration operation')
    status, data = configure_request(op, data)
    result = {'status': status}
    if data and op == 'SCAN' and status == 'OK':
        result['devices'] = decode_nodes(data)
    elif len(data) >= 120 and op in ('GET', 'PEER', 'PAIR', 'SPARE'):
        result['setup'] = decode_record(data)
        if op == 'GET' and len(data) == 122:
            result['mode'] = MODES[data[120]] if data[120] < len(MODES) else 'unknown'
            result['pending'] = data[121] != 0
    return result


def rpc(host, request):
    if host in ('', 'local', 'localhost'):
        return agent(request)
    if not HOST.fullmatch(host):
        raise ValueError('Enter a valid SSH host such as rock@192.168.1.10')
    proc = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                           '-o', 'ConnectTimeout=5', host,
                           'python3', '~/Prashant/remote/configure.py', '--agent'],
                          input=json.dumps(request), capture_output=True, text=True, timeout=55)
    if proc.returncode:
        raise OSError(proc.stderr.strip() or 'Station configuration agent failed')
    try:
        answer = json.loads(proc.stdout)
    except ValueError:
        raise OSError('Station returned an invalid configuration response') from None
    if 'error' in answer:
        raise OSError(answer['error'])
    return answer


def save_mapping(old_id, new_id, host):
    if old_id == new_id:
        return
    stations = json.loads(STATIONS.read_text()) if STATIONS.exists() else {}
    if old_id not in stations or stations[old_id] != host:
        return
    if new_id in stations and stations[new_id] != host:
        raise ValueError('Settings saved, but the new ID already maps to another station. Resolve stations.json.')
    stations[new_id] = stations.pop(old_id)
    fd, name = tempfile.mkstemp(dir=BASE, prefix='.stations-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(stations, stream, indent=2);stream.write('\n')
        os.replace(name, STATIONS)
    finally:
        if os.path.exists(name): os.unlink(name)


def run_ui():
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib

    window = Gtk.Window(title='Radxa Control | Staff configuration')
    window.set_default_size(880, 580)
    window.set_border_width(18)
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    window.add(root)
    title = Gtk.Label(label='Staff configuration', xalign=0)
    title.set_markup('<span size="x-large" weight="bold">Staff configuration</span>')
    root.pack_start(title, False, False, 0)
    grid = Gtk.Grid(column_spacing=14, row_spacing=10)
    root.pack_start(grid, False, False, 0)
    mode = Gtk.ComboBoxText()
    mode.append_text('LAN — update both ends of an existing pair')
    mode.append_text('Spare remote — configure a nearby replacement')
    mode.set_active(0)
    host = Gtk.ComboBoxText.new_with_entry()
    host.append_text('local')
    stations = json.loads(STATIONS.read_text()) if STATIONS.exists() else {}
    for name in sorted(stations): host.append_text(name)
    host.set_active(0)
    hint = Gtk.Label(label='Choose a station ID or enter rock@IP. “local” uses this Radxa.', xalign=0)
    hint.set_line_wrap(True)
    load = Gtk.Button(label='Read pair settings')
    scan = Gtk.Button(label='Start bridge / scan spares')
    spare = Gtk.ComboBoxText()
    identify = Gtk.Button(label='Identify: blink LED')
    end = Gtk.Button(label='End nearby setup')
    for row, (name, widget) in enumerate((('Mode', mode), ('Radxa / bridge', host))):
        grid.attach(Gtk.Label(label=name, xalign=0), 0, row, 1, 1)
        grid.attach(widget, 1, row, 3, 1)
    grid.attach(hint, 1, 2, 3, 1)
    grid.attach(load, 1, 3, 1, 1);grid.attach(scan, 2, 3, 1, 1);grid.attach(end, 3, 3, 1, 1)
    grid.attach(spare, 1, 4, 2, 1);grid.attach(identify, 3, 4, 1, 1)
    panel = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
    root.pack_start(panel, True, True, 0)
    fields = Gtk.Grid(column_spacing=12, row_spacing=12)
    panel.pack_start(fields, False, False, 0)
    ident = Gtk.Entry();ident.set_max_length(64)
    channel = Gtk.SpinButton.new_with_range(1, 11, 1);channel.set_value(11)
    role = Gtk.Label(label='—', xalign=0)
    profile = Gtk.Label(label='—', xalign=0)
    for row, (label, widget) in enumerate((('Device ID', ident), ('Channel', channel), ('Role (locked)', role), ('Hardware profile', profile))):
        fields.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
        fields.attach(widget, 1, row, 1, 1)
    preview = Gtk.TextView();preview.set_editable(False);preview.set_cursor_visible(False);preview.set_monospace(True)
    scroll = Gtk.ScrolledWindow();scroll.set_min_content_width(340);scroll.add(preview)
    frame = Gtk.Frame(label='setup.json preview — advanced editing reserved')
    frame.add(scroll);panel.pack_start(frame, True, True, 0)
    key = Gtk.FileChooserButton(title='Select existing fleet encryption_key.txt', action=Gtk.FileChooserAction.OPEN)
    if KEY_FILE.exists(): key.set_filename(str(KEY_FILE))
    keyrow = Gtk.Box(spacing=12);keyrow.pack_start(Gtk.Label(label='Fleet key file'), False, False, 0);keyrow.pack_start(key, True, True, 0)
    root.pack_start(keyrow, False, False, 0)
    send = Gtk.Button(label='Send configuration')
    status = Gtk.Label(label='Read the selected station, or hold S7 + S9 for 3 seconds on a spare and scan.', xalign=0)
    status.set_line_wrap(True);status.set_selectable(True)
    root.pack_start(send, False, False, 0);root.pack_start(status, False, False, 0)
    state = {'setup': None, 'host': None, 'devices': [], 'bridge': False, 'busy': False}
    controls = [mode,host,load,scan,spare,identify,end,ident,channel,key,send]

    def mode_controls():
        nearby=mode.get_active()==1
        load.set_visible(not nearby)
        for widget in (scan,spare,identify): widget.set_visible(nearby)
        end.set_visible(nearby or state['bridge'])

    def selected_host():
        value = host.get_child().get_text().strip()
        return stations.get(value, value)

    def draft():
        if not state['setup']: return None
        return {**state['setup'], 'device_id': ident.get_text().strip(), 'channel': channel.get_value_as_int()}

    def refresh(*_):
        cfg = draft()
        preview.get_buffer().set_text(json.dumps(cfg or {}, indent=2))

    def display(cfg):
        state['setup'] = cfg
        ident.set_text(cfg['device_id']);channel.set_value(cfg['channel'])
        role.set_text(cfg['role']);profile.set_text(cfg['profile']);refresh()

    def finish(result, error, callback):
        state['busy'] = False
        for widget in controls: widget.set_sensitive(True)
        if error: status.set_text('Not confirmed: ' + error)
        else:
            try: callback(result)
            except (OSError, ValueError, KeyError) as exc: status.set_text(str(exc))
        mode_controls()
        return False

    def work(message, action, callback):
        state['busy'] = True
        for widget in controls: widget.set_sensitive(False)
        status.set_text(message)
        def worker():
            try: answer=action();error=None
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc: answer=None;error=str(exc)
            GLib.idle_add(finish,answer,error,callback)
        Thread(target=worker, daemon=True).start()

    def read_pair(_):
        target=selected_host()
        state['pair_verified']=False
        def action():
            receiver=rpc(target,{'op':'GET'})
            if receiver['status']!='OK' or receiver.get('mode')!='normal': return receiver
            sender=rpc(target,{'op':'PEER'})
            return {'receiver':receiver,'sender':sender}
        def complete(answer):
            if 'receiver' not in answer: status.set_text('Station state: '+answer['status']+' / '+answer.get('mode',''));return
            receiver=answer['receiver']['setup'];sender=answer['sender']
            if receiver['role']!='receiver': raise ValueError('Selected station is not a receiver')
            state['host']=target;state['bridge']=False;display(receiver)
            matched=sender['status']=='OK' and all(sender['setup'][field]==receiver[field] for field in ('device_id','channel'))
            status.set_text('Pair settings verified on both ESPs.' if matched else 'Receiver read; sender not confirmed. Wake the sender and read again before sending.')
            state['pair_verified']=matched
        work('Reading receiver and awake sender…',action,complete)

    def scan_spares(_):
        target=selected_host()
        if state['bridge'] and target!=state['host']:
            status.set_text('End the current nearby setup before selecting another bridge.');return
        def action():
            info=rpc(target,{'op':'GET'})
            if info.get('mode')!='bridge':
                answer=rpc(target,{'op':'BRIDGE'})
                if answer['status']!='OK': return answer
            import time;time.sleep(1.5)
            return rpc(target,{'op':'SCAN'})
        def complete(answer):
            if answer['status']!='OK': status.set_text('Bridge: '+answer['status']);return
            state['bridge']=True;state['host']=target;state['devices']=answer['devices']
            spare.remove_all();state['setup']=None;refresh()
            for n in state['devices']: spare.append_text(f"{n['device_id']} · unit {n['unit'][-6:]} · {n['chip']}")
            # Selection is deliberate; do not auto-select one of several nearby remotes.
            status.set_text(f"Found {len(state['devices'])} setup-mode devices. Select one, then Identify before sending. Bridge expires after 3 minutes without activity.")
        work('Starting staff bridge and scanning channel 11…',action,complete)

    def spare_selected(_):
        i=spare.get_active()
        if 0<=i<len(state['devices']):
            node=state['devices'][i]
            display({k:node[k] for k in ('device_id','role','channel','profile')})

    def identify_spare(_):
        i=spare.get_active()
        if i<0: status.set_text('Select a spare first.');return
        node=state['devices'][i];target=state['host']
        work('Identifying selected spare…',lambda:rpc(target,{'op':'IDENTIFY','slot':node['slot'],'unit':node['unit'],'nonce':node['nonce']}),
             lambda a:status.set_text('Identify command '+a['status']+'. Check that the selected remote LED flashes quickly.'))

    def end_setup(_):
        target=state['host'] or selected_host()
        def complete(a):
            if a['status']=='OK': state['bridge']=False;state['setup']=None;spare.remove_all();refresh()
            status.set_text('End setup: '+a['status'])
        work('Restoring the bridge to normal operation…',lambda:rpc(target,{'op':'END'}),complete)

    def send_config(_):
        try:
            cfg=draft()
            if not cfg: raise ValueError('Read the pair or select a spare first.')
            validate(cfg['device_id'],cfg['channel'])
            if selected_host()!=state['host']: raise ValueError('Station selection changed. Read or scan it again.')
            keypath=key.get_filename()
            if not keypath: raise ValueError('Select the existing fleet encryption key file.')
            record=encode_record(cfg,Path(keypath).read_text().strip())
            target=state['host'];old_id=state['setup']['device_id'];lan=mode.get_active()==0
            if lan:
                if state.get('bridge') or not state.get('pair_verified'): raise ValueError('Read and verify both ESPs first.')
                if cfg['device_id'] in stations and stations[cfg['device_id']]!=target:
                    raise ValueError('That device ID already belongs to another station.')
                request={'op':'PAIR','record':record.hex()}
            else:
                i=spare.get_active()
                if i<0: raise ValueError('Select a spare.')
                n=state['devices'][i]
                request={'op':'SPARE','record':record.hex(),'slot':n['slot'],'unit':n['unit'],'nonce':n['nonce']}
        except (ValueError,OSError) as exc: status.set_text(str(exc));return
        def complete(answer):
            if answer['status']=='OK':
                display(answer['setup'])
                if lan:
                    save_mapping(old_id,cfg['device_id'],target)
                    if old_id in stations and stations[old_id]==target:
                        stations[cfg['device_id']]=stations.pop(old_id)
                        host.remove_all();host.append_text('local')
                        for name in sorted(stations): host.append_text(name)
                        host.get_child().set_text(cfg['device_id'])
                    status.set_text('Success: both ESPs saved and confirmed the Device ID and Channel. Roles preserved.')
                else:
                    spare.remove_all();state['devices']=[]
                    status.set_text('Success: spare saved and read back its settings. Switch off the old remote, then test this spare at its destination screen.')
            elif answer['status']=='ROLLED_BACK':
                state['pair_verified']=False
                status.set_text('Change not completed. Receiver retained the previous settings; read both devices again.')
            else:
                state['pair_verified']=False
                status.set_text('Not confirmed: '+answer['status']+'. Read back before retrying; do not assume the write failed.')
        work('Sending settings and waiting for saved-setting confirmation…',lambda:rpc(target,request),complete)

    def mode_changed(_):
        state['setup']=None;state['pair_verified']=False;refresh()
        role.set_text('—');profile.set_text('—');ident.set_text('');mode_controls()
        status.set_text('LAN: read both ESPs. Spare: hold S7 + S9 for 3 seconds, start bridge, scan and select.')

    def close_window(*_):
        if state['busy']:
            status.set_text('Wait for the current operation to finish before closing.');return True
        if state['bridge']:
            target=state['host']
            work('Ending staff bridge before closing…',lambda:rpc(target,{'op':'END'}),lambda _:Gtk.main_quit())
            return True
        Gtk.main_quit();return False

    ident.connect('changed',refresh);channel.connect('value-changed',refresh)
    mode.connect('changed',mode_changed);load.connect('clicked',read_pair);scan.connect('clicked',scan_spares)
    spare.connect('changed',spare_selected);identify.connect('clicked',identify_spare)
    end.connect('clicked',end_setup);send.connect('clicked',send_config)
    window.connect('delete-event',close_window)
    window.show_all();mode_controls();Gtk.main()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent', action='store_true', help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.agent:
        try:
            raw=sys.stdin.read(4097)
            if len(raw)>4096: raise ValueError('Request too large')
            request=json.loads(raw)
            if not isinstance(request,dict): raise ValueError('Expected a request object')
            print(json.dumps(agent(request)))
        except (OSError,ValueError,KeyError) as exc:
            print(json.dumps({'error':str(exc)}))
    else: run_ui()

if __name__=='__main__': main()
