"""Configuration compatibility, target selection and UART framing regression tests."""
import contextlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'radxa'), str(ROOT/'firmware')]
import configure
import generate_key
import setup_board
from configuration_model import encode_record, decode_record, decode_nodes, selection, NODE
from setup_board import board_record, build_partition
from radxa_receiver import Receiver, StationFrames

KEY = 'a5' * 16  # Public test key; never use for a real device.
SETUP = dict(device_id='test-001', role='receiver', channel=11, profile='presenter-matrix')


class Configuration(unittest.TestCase):
    def test_fresh_checkout_and_repeat_preserve_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);key=data/'encryption_key.txt';setup=data/'setup.json'
            with patch.multiple(generate_key,DATA=data,KEY_FILE=key), patch.object(setup_board,'KEY_FILE',key), contextlib.redirect_stdout(io.StringIO()):
                generate_key.main()
                self.assertEqual(json.loads(setup.read_text()),dict(device_id='remote-001',role='sender',channel=11))
                saved=key.read_bytes()
                self.assertEqual(len(bytes.fromhex(saved.decode().strip())),16)
                setup.write_text(json.dumps({**SETUP,'device_id':'staff-kept-002','channel':3}))
                original=setup.read_bytes()
                generate_key.main()
                self.assertEqual(key.read_bytes(),saved);self.assertEqual(setup.read_bytes(),original)
                for target in ('esp32','esp32c3'):
                    output=data/(target+'.bin')
                    build_partition(setup,target,output)
                    self.assertEqual(decode_record(output.read_bytes()),{**SETUP,'device_id':'staff-kept-002','channel':3})

    def test_conflicting_key_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);key=data/'encryption_key.txt';setup=data/'setup.json'
            key.write_text(KEY+'\n');setup.write_text(json.dumps({**SETUP,'master_key':'5a'*16}))
            original=setup.read_bytes()
            with patch.multiple(generate_key,DATA=data,KEY_FILE=key), self.assertRaises(ValueError):generate_key.main()
            self.assertEqual(key.read_text(),KEY+'\n');self.assertEqual(setup.read_bytes(),original)

    def test_factory_and_staff_records_match(self):
        for role in ('sender','receiver'):
            for channel in (1,3,6,11):
                cfg={**SETUP,'role':role,'channel':channel}
                self.assertEqual(encode_record(cfg,KEY), board_record({**cfg,'master_key':KEY},generation=bytes(4))[2])
                self.assertEqual(decode_record(encode_record(cfg,KEY)),cfg)

    def test_bad_settings(self):
        for fields in ({'channel':True},{'channel':12},{'channel':0},{'device_id':'-bad'},
                       {'device_id':'a'*65},{'device_id':'bad name'},{'role':'admin'},{'profile':'unknown'}):
            with self.assertRaises(ValueError): encode_record({**SETUP,**fields},KEY)
        with self.assertRaises(ValueError): decode_record(b'bad')

    def test_fleet_extension_and_rebuild_stability(self):
        with tempfile.TemporaryDirectory() as folder:
            setup=Path(folder)/'setup.json';out=Path(folder)/'paircfg.bin'
            setup.write_text(json.dumps({**SETUP,'master_key':KEY}))
            with contextlib.redirect_stdout(io.StringIO()):
                build_partition(setup,'esp32c3',out);first=out.read_bytes()
                build_partition(setup,'esp32c3',out)
            self.assertEqual(first,out.read_bytes())
            self.assertEqual(first[:120],encode_record(SETUP,KEY))
            self.assertEqual(first[256:260],b'SET1')
            self.assertEqual(struct.unpack('<I',first[276:280])[0],zlib.crc32(first[260:276]))

    def node(self):
        return NODE.pack(bytes.fromhex('24587c8400d8'),123,1,11,1,3,3,b'spare-001') + bytes(5*NODE.size)

    def test_selection_binds_physical_unit_and_setup_session(self):
        node=decode_nodes(self.node())[0]
        self.assertEqual(selection(node),b'\0'+bytes.fromhex(node['unit'])+struct.pack('<Q',123))
        for fields in ({'slot':6},{'slot':True},{'nonce':'0'*16},{'unit':'abc'}):
            with self.assertRaises(ValueError): selection({**node,**fields})

    def test_spare_recheck_and_uart_selection(self):
        node=decode_nodes(self.node())[0]
        record=encode_record({**SETUP,'role':'sender'},KEY)
        calls=[]
        def uart(op,data=b''):
            calls.append((op,data))
            return ('OK',self.node()) if op=='SCAN' else ('OK',record)
        with patch.object(configure,'configure_request',uart):
            result=configure.agent({'op':'SPARE',**node,'record':record.hex()})
            self.assertEqual(result['setup']['role'],'sender')
            self.assertEqual(calls[-1],('SPARE',selection(node)+record))
            with self.assertRaises(ValueError):
                configure.agent({'op':'SPARE',**node,'nonce':'0000000000000001','record':record.hex()})
        self.assertEqual([op for op,_ in calls],['SCAN','SPARE','SCAN'])
        self.assertNotIn('record',json.dumps(result))

    def test_config_frames_interleaved_with_buttons(self):
        replies=[];events=[];acks=[]
        class Control:
            def reply(self,line): replies.append(line)
        frames=StationFrames(Receiver(events.append),Control())
        response=b'RCFG 12345678 OK '+self.node().hex().encode()+b'\n'
        stream=response+b'EV 00000001 00000002 1 4 0 3000\n'+b'X'*1600+b'\n'+b'EV 00000001 00000002 1 4 0 3000\n'
        for start in range(0,len(stream),37): frames.feed(stream[start:start+37],acks.append)
        self.assertEqual(replies,[response.rstrip()]);self.assertEqual(len(events),1)
        self.assertEqual(acks,[b'ACK 00000001 00000002\n']*2)

if __name__=='__main__': unittest.main()
