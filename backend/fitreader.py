"""
fitreader.py — minimální dekodér FIT souborů bez závislostí.

Proč vlastní dekodér a ne jen garmin-fit-sdk:
  Oficiální SDK je lepší volba do produkce a `garmin_ingest.py` ho použije,
  pokud je nainstalovaný. Tenhle modul je fallback, aby ingest fungoval
  i na stroji bez pip installu — a hlavně aby bylo vidět, že jediná
  metrika, kterou JSON export Garminu neobsahuje (stance time balance),
  se z FIT dostat dá.

Pokrývá čtení message typů, které platforma potřebuje:
  session (18), lap (19), record (20)

Formát: https://developer.garmin.com/fit/protocol/
"""
import struct, os
from datetime import datetime, timezone, timedelta

FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)

# base type -> (struct char, size, invalid value)
BASE_TYPES = {
    0x00: ('B', 1, 0xFF),        # enum
    0x01: ('b', 1, 0x7F),        # sint8
    0x02: ('B', 1, 0xFF),        # uint8
    0x83: ('h', 2, 0x7FFF),      # sint16
    0x84: ('H', 2, 0xFFFF),      # uint16
    0x85: ('i', 4, 0x7FFFFFFF),  # sint32
    0x86: ('I', 4, 0xFFFFFFFF),  # uint32
    0x07: ('s', 1, 0x00),        # string
    0x88: ('f', 4, 0xFFFFFFFF),  # float32
    0x89: ('d', 8, 0xFFFFFFFF),  # float64
    0x0A: ('B', 1, 0x00),        # uint8z
    0x8B: ('H', 2, 0x0000),      # uint16z
    0x8C: ('I', 4, 0x00000000),  # uint32z
    0x0D: ('B', 1, 0xFF),        # byte
    0x8E: ('q', 8, 0x7FFFFFFFFFFFFFFF),
    0x8F: ('Q', 8, 0xFFFFFFFFFFFFFFFF),
    0x90: ('Q', 8, 0x0000000000000000),
}

# global message number -> {field def num: (name, scale, offset)}
SESSION = 18
LAP = 19
RECORD = 20

FIELDS = {
    SESSION: {
        2:   ('start_time', 1, 0),
        5:   ('sport', 1, 0),
        6:   ('sub_sport', 1, 0),
        7:   ('total_elapsed_time', 1000, 0),
        8:   ('total_timer_time', 1000, 0),
        9:   ('total_distance', 100, 0),
        16:  ('avg_heart_rate', 1, 0),
        17:  ('max_heart_rate', 1, 0),
        18:  ('avg_cadence', 1, 0),
        21:  ('total_ascent', 1, 0),
        22:  ('total_descent', 1, 0),
        57:  ('avg_temperature', 1, 0),
        89:  ('avg_vertical_oscillation', 10, 0),      # mm
        90:  ('avg_stance_time_percent', 100, 0),
        91:  ('avg_stance_time', 10, 0),               # ms
        132: ('avg_vertical_ratio', 100, 0),           # %
        133: ('avg_stance_time_balance', 100, 0),      # % left
        134: ('avg_step_length', 10, 0),               # mm
    },
    LAP: {
        2:   ('start_time', 1, 0),
        7:   ('total_elapsed_time', 1000, 0),
        9:   ('total_distance', 100, 0),
        15:  ('avg_heart_rate', 1, 0),
        17:  ('avg_cadence', 1, 0),
        21:  ('total_ascent', 1, 0),
        22:  ('total_descent', 1, 0),
        77:  ('avg_vertical_oscillation', 10, 0),
        78:  ('avg_stance_time_percent', 100, 0),
        79:  ('avg_stance_time', 10, 0),
        113: ('avg_vertical_ratio', 100, 0),
        114: ('avg_stance_time_balance', 100, 0),
        115: ('avg_step_length', 10, 0),
    },
    RECORD: {
        253: ('timestamp', 1, 0),
        2:   ('altitude', 5, 500),                     # m — 16-bit, most devices
        3:   ('heart_rate', 1, 0),
        4:   ('cadence', 1, 0),
        5:   ('distance', 100, 0),
        6:   ('speed', 1000, 0),
        39:  ('vertical_oscillation', 10, 0),
        40:  ('stance_time_percent', 100, 0),
        41:  ('stance_time', 10, 0),
        78:  ('enhanced_altitude', 5, 500),             # m — 32-bit, preferred when present
        132: ('vertical_ratio', 100, 0),
        133: ('stance_time_balance', 100, 0),
        134: ('step_length', 10, 0),
    },
}


class FitError(Exception):
    pass


def _ts(v):
    if v is None:
        return None
    return (FIT_EPOCH + timedelta(seconds=v)).isoformat()


def decode(path, want=(SESSION, LAP)):
    """Vrátí {'session': [...], 'lap': [...], 'record': [...]}."""
    with open(path, 'rb') as fh:
        buf = fh.read()
    if len(buf) < 14:
        raise FitError('soubor je kratší než hlavička FIT')

    hdr_size = buf[0]
    if buf[8:12] != b'.FIT':
        raise FitError('chybí signatura .FIT')
    data_size = struct.unpack('<I', buf[4:8])[0]
    pos = hdr_size
    end = min(hdr_size + data_size, len(buf))

    defs = {}           # local msg type -> definition
    out = {'session': [], 'lap': [], 'record': []}
    name_of = {SESSION: 'session', LAP: 'lap', RECORD: 'record'}

    while pos < end:
        header = buf[pos]; pos += 1

        if header & 0x40:                     # definition message
            local = header & 0x0F
            developer = bool(header & 0x20)
            pos += 1                          # reserved
            arch = buf[pos]; pos += 1
            endian = '>' if arch == 1 else '<'
            gmn = struct.unpack(endian + 'H', buf[pos:pos+2])[0]; pos += 2
            nfields = buf[pos]; pos += 1
            fields = []
            for _ in range(nfields):
                fdn, size, btype = buf[pos], buf[pos+1], buf[pos+2]
                pos += 3
                fields.append((fdn, size, btype))
            dev_fields = []
            if developer:
                ndev = buf[pos]; pos += 1
                for _ in range(ndev):
                    dev_fields.append((buf[pos], buf[pos+1], buf[pos+2]))
                    pos += 3
            defs[local] = (gmn, endian, fields, dev_fields)

        else:                                  # data message
            local = header & 0x0F
            if header & 0x80:                  # compressed timestamp header
                local = (header >> 5) & 0x03
            if local not in defs:
                raise FitError('datová zpráva bez definice')
            gmn, endian, fields, dev_fields = defs[local]
            keep = gmn in want and gmn in FIELDS
            rec = {} if keep else None
            fmap = FIELDS.get(gmn, {})

            for fdn, size, btype in fields:
                raw = buf[pos:pos+size]; pos += size
                if not keep or fdn not in fmap:
                    continue
                bt = BASE_TYPES.get(btype)
                if bt is None:
                    continue
                ch, esize, invalid = bt
                if ch == 's':
                    val = raw.split(b'\x00')[0].decode('utf-8', 'ignore') or None
                else:
                    n = size // esize
                    if n < 1:
                        continue
                    try:
                        vals = struct.unpack(endian + ch * n, raw[:esize*n])
                    except struct.error:
                        continue
                    val = vals[0]
                    if val == invalid:
                        val = None
                if val is None:
                    continue
                name, scale, offset = fmap[fdn]
                if isinstance(val, (int, float)) and ch not in 'sfd':
                    val = val / scale - offset if scale != 1 else val
                if name in ('start_time', 'timestamp'):
                    val = _ts(val)
                rec[name] = val

            for fdn, size, btype in dev_fields:
                pos += size

            if keep and rec:
                out[name_of[gmn]].append(rec)

    return out


def _elevation_profile(records, max_points=80):
    """Distance/altitude stream downsampled to `max_points` — 2.5%-wide
    gradient bands don't need a full 1Hz stream, and storing one would
    bloat every activity row for no analytical benefit. Prefers
    enhanced_altitude (32-bit) over altitude (16-bit) per record."""
    pts = []
    for rec in records:
        dist = rec.get('distance')
        alt = rec.get('enhanced_altitude')
        if alt is None:
            alt = rec.get('altitude')
        if dist is None or alt is None:
            continue
        pts.append((dist, alt))
    if len(pts) < 2:
        return None
    total_dist = pts[-1][0] - pts[0][0]
    if total_dist <= 0:
        return None
    step = max(total_dist / max_points, 1)
    out = [{'distance_m': round(pts[0][0], 1), 'altitude_m': round(pts[0][1], 1)}]
    next_mark = pts[0][0] + step
    for dist, alt in pts[1:]:
        if dist >= next_mark:
            out.append({'distance_m': round(dist, 1), 'altitude_m': round(alt, 1)})
            next_mark = dist + step
    last = pts[-1]
    if out[-1]['distance_m'] != round(last[0], 1):
        out.append({'distance_m': round(last[0], 1), 'altitude_m': round(last[1], 1)})
    return out


def running_dynamics(path):
    """Zkrácený pohled: jedna session + laps, přepočtené do jednotek platformy."""
    d = decode(path, want=(SESSION, LAP, RECORD))
    if not d['session']:
        return None
    s = d['session'][0]
    if s.get('sport') not in (1, None):        # 1 = running
        return None
    dist_m = s.get('total_distance') or 0
    dur_s = s.get('total_timer_time') or 0
    if dist_m < 500 or dur_s < 120:
        return None
    cad = s.get('avg_cadence')
    return {
        'source': 'fit',
        'file': os.path.basename(path),
        'started_at': (s.get('start_time') or '')[:10],
        'distance_km': round(dist_m / 1000, 2),
        'duration_min': round(dur_s / 60, 1),
        'pace_s_km': round(dur_s / (dist_m / 1000)) if dist_m else None,
        'avg_hr': s.get('avg_heart_rate'),
        'cadence_spm': round(cad * 2) if cad else None,   # FIT ukládá kroky jedné nohy
        'stride_len_m': round(s['avg_step_length'] / 1000, 2) if s.get('avg_step_length') else None,
        'vert_osc_cm': round(s['avg_vertical_oscillation'] / 10, 2) if s.get('avg_vertical_oscillation') else None,
        'vert_ratio_pct': s.get('avg_vertical_ratio'),
        'gct_ms': s.get('avg_stance_time'),
        # tohle JSON export Garminu neobsahuje — jediný zdroj je FIT
        'gct_balance_l': s.get('avg_stance_time_balance'),
        'ascent_m': s.get('total_ascent'),
        'descent_m': s.get('total_descent'),
        'temp_c': s.get('avg_temperature'),
        'elevation_profile': _elevation_profile(d['record']),
        'laps': [{
            'km': round((l.get('total_distance') or 0) / 1000, 2),
            'vert_ratio_pct': l.get('avg_vertical_ratio'),
            'gct_ms': l.get('avg_stance_time'),
            'gct_balance_l': l.get('avg_stance_time_balance'),
            'avg_hr': l.get('avg_heart_rate'),
        } for l in d['lap']],
    }


if __name__ == '__main__':
    import sys, json
    for p in sys.argv[1:]:
        try:
            r = running_dynamics(p)
            print(json.dumps(r, ensure_ascii=False)[:600] if r else f'{p}: není běh')
        except FitError as e:
            print(f'{p}: {e}')
