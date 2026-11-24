"""Open the actual GTK configuration form and verify locked fields; no device writes."""
import sys
from pathlib import Path
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk, GLib, Gdk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import configure

errors=[];attempts=0
def inspect():
    global attempts
    try:
        win=next(w for w in Gtk.Window.list_toplevels() if w.get_title()=='Radxa Control | Staff configuration')
        def children(w):
            yield w
            if isinstance(w,Gtk.Container):
                for c in w.get_children(): yield from children(c)
        widgets=list(children(win))
        previews=[w for w in widgets if isinstance(w,Gtk.TextView)]
        assert len(previews)==1 and not previews[0].get_editable()
        if '--live' in sys.argv:
            buffer=previews[0].get_buffer()
            value=buffer.get_text(buffer.get_start_iter(),buffer.get_end_iter(),True)
            if 'remote-001' not in value and attempts<40:
                attempts+=1;return True
            assert 'remote-001' in value and 'receiver' in value and '11' in value, value
        labels=[w.get_label() for w in widgets if isinstance(w,Gtk.Label)]
        assert 'Role (locked)' in labels and 'Device ID' in labels
        assert len([w for w in widgets if isinstance(w,Gtk.Button) and w.get_label()=='Send configuration'])==1
        if len(sys.argv)>1 and not sys.argv[1].startswith('--'):
            Gdk.pixbuf_get_from_window(win.get_window(),0,0,win.get_allocated_width(),win.get_allocated_height()).savev(sys.argv[1],'png',[],[])
        print('PASS: staff UI opens; JSON preview read-only; role locked',flush=True)
        if '--live' in sys.argv: print('PASS: actual UI Read pair settings verified remote-001 / channel 11 via the running receiver',flush=True)
    except Exception as exc: errors.append(exc)
    Gtk.main_quit();return False
def read_live():
    def click(w):
        if isinstance(w,Gtk.Button) and w.get_label()=='Read pair settings':w.clicked()
        if isinstance(w,Gtk.Container):
            for c in w.get_children():click(c)
    for win in Gtk.Window.list_toplevels():click(win)
    return False
if '--live' in sys.argv:GLib.timeout_add(400,read_live)
GLib.timeout_add(250 if '--live' in sys.argv else 1200,inspect)
configure.run_ui()
if errors: raise errors[0]
