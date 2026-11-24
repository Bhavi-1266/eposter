"""Exercise the real receiver process and staff client on a Linux pseudo-terminal."""
import os, pty, select, subprocess, sys, tempfile, time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as work:
    env = {**os.environ, "XDG_RUNTIME_DIR":work, "PYTHONDONTWRITEBYTECODE":"1"}
    master, slave = pty.openpty()
    receiver = subprocess.Popen([sys.executable, str(root/"remote"), "start", "--port", os.ttyname(slave)], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    os.close(slave)
    try:
        for _ in range(100):
            if (Path(work)/"radxa-remote/control.sock").exists(): break
            if receiver.poll() is not None: raise RuntimeError(receiver.stderr.read().decode())
            time.sleep(.04)
        def readline():
            buf=b""
            deadline=time.monotonic()+4
            while b"\n" not in buf:
                if not select.select([master],[],[],max(0,deadline-time.monotonic()))[0]:
                    raise AssertionError("UART timeout")
                buf+=os.read(master,1)
            return buf
        for _ in range(2):
            os.write(master,b"EV 00000001 00000002 1 4 0 3000\n")
            assert readline()==b"ACK 00000001 00000002\n"
        for ident, outcome in [("remote-001",b"OK 11"),("remote-002",b"WRONG_ID 0")]:
            ctl=subprocess.Popen([sys.executable,str(root/"remote"),"channel",ident,"11"],env=env,stdout=subprocess.PIPE)
            msg=readline().split()
            assert msg[0]==b"CHANNEL" and msg[2:]==[ident.encode(),b"11"]
            os.write(master,b"CHANNEL "+msg[1]+b" "+outcome+b"\n")
            result=ctl.communicate(timeout=6)[0]
            assert outcome.split()[0] in result and ctl.returncode==(0 if outcome.startswith(b"OK") else 1)
        ctl=subprocess.Popen([sys.executable,str(root/'configure.py'),'--agent'],env=env,
                             stdin=subprocess.PIPE,stdout=subprocess.PIPE)
        ctl.stdin.write(b'{"op":"SCAN"}');ctl.stdin.close();ctl.stdin=None
        msg=readline().split()
        assert msg[0]==b'RCFG' and msg[2:]==[b'SCAN',b'-']
        # Wrong token is ignored; a normal button remains actionable during RPC.
        os.write(master,b'RCFG ffffffff OK -\nEV 00000001 00000003 1 4 0 3000\n')
        assert readline()==b'ACK 00000001 00000003\n'
        payload=b'00'*(6*84)
        line=b'RCFG '+msg[1]+b' OK '+payload+b'\n'
        for start in range(0,len(line),41): os.write(master,line[start:start+41])
        result=ctl.communicate(timeout=6)[0]
        assert b'"devices": []' in result and b'"status": "OK"' in result
        print("PASS: station listener, button/retry ACK, live UART staff channel command and wrong-ID reporting")
        print('PASS: configuration RPC, long discovery response, unrelated token rejection and concurrent button ACK')
    finally:
        receiver.terminate()
        receiver.wait(timeout=4)
        os.close(master)
