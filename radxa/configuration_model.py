"""Configuration wire format and validation. Never print a binary record: it contains keys."""
import hashlib
import hmac
import re
import struct

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
HOST = re.compile(r"(?:[A-Za-z0-9_][\w.-]*@)?[A-Za-z0-9][A-Za-z0-9.:-]*")
PROFILES = ('presenter-two-button', 'presenter-matrix', 'crowd', 'presenter-one-button')
ROLES = ('sender', 'receiver')
RECORD = struct.Struct('<4sBB6s6s16s16sB4s65s')
NODE = struct.Struct('<6sQBBBBB65s')
MODES = ('normal', 'pair-change', 'bridge', 'spare')


def selection(request):
    slot, unit, nonce = (request.get(k) for k in ('slot', 'unit', 'nonce'))
    if (type(slot) is not int or not 0 <= slot < 6 or not isinstance(unit, str) or
            not re.fullmatch('[0-9A-Fa-f]{12}', unit) or not isinstance(nonce, str) or
            not re.fullmatch('[0-9a-f]{16}', nonce) or int(nonce, 16) == 0):
        raise ValueError('Scan and select a current spare first')
    return bytes([slot]) + bytes.fromhex(unit) + struct.pack('<Q', int(nonce, 16))


def validate(device_id, channel):
    if not isinstance(device_id, str) or not ID.fullmatch(device_id):
        raise ValueError('Device ID: 1–64 letters, numbers, dashes, dots or underscores; start with a letter/number.')
    if type(channel) is not int or not 1 <= channel <= 11:
        raise ValueError('Channel must be an integer from 1 to 11.')


def decode_record(data):
    if len(data) < RECORD.size:
        raise ValueError('Incomplete device settings')
    magic, role, channel, local, peer, pmk, lmk, profile, generation, name = RECORD.unpack(data[:120])
    if magic != b'RCF2' or role not in (1, 2) or profile >= len(PROFILES) or b'\0' not in name:
        raise ValueError('Invalid device settings')
    device_id = name.split(b'\0', 1)[0].decode('ascii')
    validate(device_id, channel)
    if local[0] & 3 != 2 or peer[0] & 3 != 2 or local == peer:
        raise ValueError('Invalid binding addresses')
    return {'device_id': device_id, 'role': ROLES[role-1], 'channel': channel, 'profile': PROFILES[profile]}


def encode_record(settings, master_key):
    validate(settings['device_id'], settings['channel'])
    if not isinstance(master_key, str) or not re.fullmatch('[0-9a-fA-F]{32}', master_key):
        raise ValueError('Load the existing fleet encryption_key.txt (32 hexadecimal characters).')
    if settings['role'] not in ROLES or settings['profile'] not in PROFILES:
        raise ValueError('Unsupported role or hardware profile')
    digest = hashlib.sha256(b'radxa-control/espnow/address/v1/' + settings['device_id'].encode()).digest()
    sender = bytes([(digest[0] & 0xf8) | 2]) + digest[1:6]
    receiver = bytes([sender[0] | 4]) + sender[1:]
    role = ROLES.index(settings['role'])
    keys = [hmac.digest(bytes.fromhex(master_key),
            f"radxa-control/espnow/v1/{settings['device_id']}/{purpose}".encode(), 'sha256')[:16]
            for purpose in ('pmk', 'lmk')]
    addresses = (sender, receiver)
    return RECORD.pack(b'RCF2', role+1, settings['channel'], addresses[role], addresses[1-role],
                       *keys, PROFILES.index(settings['profile']), bytes(4), settings['device_id'].encode())


def decode_nodes(data):
    if len(data) != 6 * NODE.size:
        raise ValueError('Incomplete discovery result')
    nodes = []
    for slot in range(6):
        mac, nonce, role, channel, profile, chip, mode, name = NODE.unpack_from(data, slot * NODE.size)
        if not nonce:
            continue
        if role not in (1, 2) or profile >= len(PROFILES) or mode != 3 or chip not in (3, 32):
            raise ValueError('Invalid discovered device')
        device_id = name.split(b'\0', 1)[0].decode('ascii')
        validate(device_id, channel)
        nodes.append(dict(slot=slot, unit=mac.hex().upper(), nonce=f'{nonce:016x}', device_id=device_id,
                          role=ROLES[role-1], channel=channel, profile=PROFILES[profile],
                          chip='esp32c3' if chip == 3 else 'esp32'))
    return nodes
