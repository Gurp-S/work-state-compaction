"""Length-delimited bridge frames. No credentials or remote endpoint in frames."""
import json
import struct

MAX_FRAME = 24 * 1024 * 1024


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value: raise ValueError('provider_bridge_duplicate_key')
        value[key] = item
    return value


def loads(raw):
    return json.loads(raw, object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('provider_bridge_nonfinite')))


def exact(stream, size):
    parts = []; remaining = size
    while remaining:
        block = stream.read(remaining)
        if not block: raise EOFError('provider_bridge_frame_truncated')
        parts.append(block); remaining -= len(block)
    return b''.join(parts)


def receive(stream):
    size = struct.unpack('!I', exact(stream, 4))[0]
    if not 0 < size <= MAX_FRAME: raise ValueError('provider_bridge_frame_size')
    value = loads(exact(stream, size).decode('utf-8'))
    if type(value) is not dict: raise ValueError('provider_bridge_frame_shape')
    return value


def send(stream, value):
    raw = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode()
    if not 0 < len(raw) <= MAX_FRAME: raise ValueError('provider_bridge_frame_size')
    stream.write(struct.pack('!I', len(raw))); stream.write(raw); stream.flush()
