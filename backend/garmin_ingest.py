#!/usr/bin/env python3
"""
garmin_ingest.py — převede skutečný Garmin export do schématu platformy.

Vstup:  ZIP z Garmin Connect → Account → Export Your Data (GDPR export)
        nebo už rozbalená složka
Výstup: seed JSON, který sní `core.js` beze změny

Použití:
    python garmin_ingest.py export.zip -o user_seed.json
    python garmin_ingest.py export.zip -o user_seed.json --fit    # + sken FIT souborů

Dvě cesty ke stejným datům a proč na tom záleží:

  summarizedActivities.json   rychlé, jeden soubor, obsahuje vertikální poměr,
                              vertikální oscilaci, GCT, délku kroku, kadenci
                              i úseky (splits) → stačí na 13 ze 14 metrik

  FIT soubory                 jediný zdroj `avg_stance_time_balance`, tedy
                              metriky symetrie kontaktu. Pozor: pole existuje
                              i u hodinek, které ho neumí změřit — zůstane
                              prázdné. Měření symetrie vyžaduje hrudní pás
                              HRM-Pro/HRM-Run nebo Running Dynamics Pod.
                              Ingest to pozná a nahlásí místo tichého selhání.

Oficiální SDK se použije, pokud je k dispozici (pip install garmin-fit-sdk).
Jinak se sáhne po vestavěném dekodéru fitreader.py, aby ingest fungoval
i bez instalace.
"""
import argparse, glob, json, os, shutil, statistics, sys, tempfile, zipfile
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from garmin_fit_sdk import Decoder, Stream
    HAVE_SDK = True
except ImportError:
    HAVE_SDK = False
try:
    import fitreader
    HAVE_FALLBACK = True
except ImportError:
    HAVE_FALLBACK = False

CM, MS = 100.0, 1000.0


def r(v, n=2):
    return round(v, n) if isinstance(v, (int, float)) else None


def pos(v, n=2):
    """0 / negative = missing sensor reading (see garmin_live._pos). For
    running-dynamics + HR fields a 0 means the pod/watch didn't capture it."""
    return round(v, n) if isinstance(v, (int, float)) and v > 0 else None


def iso_of(ms_ts):
    return datetime.fromtimestamp(ms_ts / 1000, tz=timezone.utc).date().isoformat()


def start_fields(a):
    """Local start time (HH:MM) and start coordinates rounded to ~1 km.
    startTimeLocal in the export is the local wall-clock time encoded as epoch ms,
    so reading it as UTC yields the local HH:MM."""
    out = {}
    t = a.get('startTimeLocal')
    if isinstance(t, (int, float)):
        out['start_time'] = datetime.fromtimestamp(t / 1000, tz=timezone.utc).strftime('%H:%M')
    lat, lon = a.get('startLatitude'), a.get('startLongitude')
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and (lat or lon):
        out['start_lat'], out['start_lon'] = round(lat, 2), round(lon, 2)
    return out


# ---------------------------------------------------------------- activities
SURFACE = {'trail_running': 'trail', 'treadmill_running': 'treadmill',
           'track_running': 'track', 'indoor_running': 'treadmill'}


def split_measure(sp, field):
    for m in sp.get('measurements', []):
        if m.get('fieldEnum') == field and m.get('valid'):
            return m.get('value')
    return None


def thirds_from_splits(splits):
    """Rozdělí úseky na třetiny → vstup pro intra-run decoupling."""
    usable = [s for s in splits or [] if split_measure(s, 'WEIGHTED_MEAN_VERTICAL_RATIO')]
    if len(usable) < 3:
        return None, None, None
    n = len(usable)
    cut = [usable[:n // 3], usable[n // 3:2 * n // 3], usable[2 * n // 3:]]

    def avg(group, field, scale=1.0):
        vals = [split_measure(s, field) for s in group]
        vals = [v / scale for v in vals if v is not None]
        return r(statistics.fmean(vals)) if vals else None

    vr = [avg(g, 'WEIGHTED_MEAN_VERTICAL_RATIO') for g in cut]
    hr = [avg(g, 'WEIGHTED_MEAN_HEARTRATE') for g in cut]
    sp = [avg(g, 'WEIGHTED_MEAN_SPEED') for g in cut]
    if None in vr:
        return None, None, None
    pace = [r(1000 / (s * 10)) if s else None for s in sp]   # cm/ms → s/km
    if None in pace:
        pace = None
    if None in (hr or [None]):
        hr = None
    return vr, hr, pace


CROSS_SPORT = {
    'cycling': 'cycling', 'road_biking': 'cycling', 'mountain_biking': 'cycling', 'indoor_cycling': 'cycling',
    'lap_swimming': 'swimming', 'open_water_swimming': 'swimming', 'swimming': 'swimming',
    'strength_training': 'strength', 'rowing': 'rowing', 'indoor_rowing': 'rowing',
    'elliptical': 'elliptical', 'hiking': 'hiking', 'walking': 'walking',
}


def sport_of(atype):
    t = (atype or '').lower()
    if 'running' in t:
        return 'running'
    for k, s in CROSS_SPORT.items():
        if k in t:
            return s
    if 'cycl' in t or 'biking' in t:
        return 'cycling'
    if 'swim' in t:
        return 'swimming'
    if 'strength' in t:
        return 'strength'
    if 'row' in t:
        return 'rowing'
    if 'walk' in t:
        return 'walking'
    if 'hik' in t:
        return 'hiking'
    return 'other'


def load_activities(root, runner_id):
    hits = glob.glob(os.path.join(root, '**', '*summarizedActivities.json'), recursive=True)
    if not hits:
        return [], {}
    with open(hits[0], encoding='utf-8') as fh:
        blob = json.load(fh)
    raw = blob[0]['summarizedActivitiesExport'] if isinstance(blob, list) else blob

    acts, aid = [], 1
    for a in raw:
        atype = str(a.get('activityType', ''))
        sport = sport_of(atype)
        dist_m = (a.get('distance') or 0) / CM
        dur_s = (a.get('duration') or 0) / MS
        if sport != 'running':                          # cross-training: load only
            if dur_s < 600:
                continue
            km_c = dist_m / 1000 if dist_m else None
            acts.append({
                'id': aid, 'runner_id': runner_id, 'provider': 'garmin_export',
                'external_id': a.get('activityId'),
                'started_at': iso_of(a.get('startTimeLocal') or a.get('beginTimestamp')),
                'title': a.get('name') or sport, 'sport': sport,
                'distance_km': r(km_c) if km_c else None,
                'duration_min': r(dur_s / 60, 1),
                'avg_hr': pos(a.get('avgHr'), 0),
                'training_load': r(a.get('activityTrainingLoad'), 1),
                **start_fields(a),
            })
            aid += 1
            continue
        if dist_m < 800 or dur_s < 240:                 # rozcvičky a chyby měření ven
            continue
        km = dist_m / 1000
        vr, hr3, pace3 = thirds_from_splits(a.get('splits'))
        rpe = a.get('workoutRpe')
        feel = a.get('workoutFeel')
        acts.append({
            'id': aid,
            'runner_id': runner_id,
            'provider': 'garmin_export',
            'external_id': a.get('activityId'),
            'started_at': iso_of(a.get('startTimeLocal') or a.get('beginTimestamp')),
            'title': a.get('name') or 'Běh', 'sport': 'running',
            'distance_km': r(km),
            'duration_min': r(dur_s / 60, 1),
            'pace_s_km': round(dur_s / km) if km else None,
            'avg_hr': pos(a.get('avgHr'), 0),
            'surface': SURFACE.get(atype, 'road'),
            'ascent_m': round((a.get('elevationGain') or 0) / CM),
            'descent_m': round((a.get('elevationLoss') or 0) / CM),
            'temp_c': r(a.get('minTemperature'), 0),
            'cadence_spm': pos(a.get('avgDoubleCadence'), 0),
            'stride_len_m': pos((a.get('avgStrideLength') or 0) / CM),
            'vert_osc_cm': pos(a.get('avgVerticalOscillation')),
            'vert_ratio_pct': pos(a.get('avgVerticalRatio')),
            'gct_ms': pos(a.get('avgGroundContactTime'), 0),
            'gct_balance_l': None,                       # jen z FIT, viz --fit
            'vr_thirds': vr,
            'hr_thirds': hr3,
            'pace_thirds': pace3,
            'rpe': round(rpe / 10) if rpe else None,      # Garmin 0–100 → 1–10
            'feel_garmin': round(feel / 20) if feel else None,   # 0–100 → 1–5
            'training_load': r(a.get('activityTrainingLoad'), 1),
            'vo2max': r(a.get('vO2MaxValue'), 1),
            **start_fields(a),
        })
        aid += 1

    acts.sort(key=lambda x: x['started_at'])
    for i, a in enumerate(acts, 1):
        a['id'] = i
    return acts, {'file': os.path.basename(hits[0]), 'total_in_export': len(raw)}


# ------------------------------------------------------------ daily metrics
def load_daily(root, runner_id):
    out, did = {}, 1
    for path in glob.glob(os.path.join(root, '**', 'UDSFile_*.json'), recursive=True):
        with open(path, encoding='utf-8') as fh:
            for d in json.load(fh):
                day = d.get('calendarDate')
                if not day:
                    continue
                bb = d.get('bodyBattery') or {}
                stress = d.get('allDayStress') or {}
                agg = (stress.get('aggregatorList') or [{}])[0]
                out[day] = {
                    'id': did, 'runner_id': runner_id, 'date': day,
                    'sleep_h': None,                       # doplní sleep parser níž
                    'hrv_ms': None,
                    'resting_hr': d.get('restingHeartRate') or d.get('currentDayRestingHeartRate'),
                    'body_battery': bb.get('bodyBatteryStatList', [{}])[0].get('statsValue')
                                    if bb.get('bodyBatteryStatList') else None,
                    'stress_avg': agg.get('averageStressLevel'),
                    'steps': d.get('totalSteps'),
                    'source': 'garmin', 'original_sleep_h': None,
                    'edited_at': None, 'edit_note': None,
                }
                did += 1

    # spánek: v exportu bývá buď v sleepData.json, nebo vůbec (podle typu hodinek)
    for path in glob.glob(os.path.join(root, '**', '*sleepData.json'), recursive=True):
        try:
            with open(path, encoding='utf-8') as fh:
                rows = json.load(fh)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for s in rows if isinstance(rows, list) else []:
            day = s.get('calendarDate') or s.get('sleepStartTimestampLocal')
            secs = s.get('sleepTimeSeconds') or s.get('deepSleepSeconds')
            if day and secs and day in out:
                out[day]['sleep_h'] = r(secs / 3600, 1)

    rows = sorted(out.values(), key=lambda x: x['date'])
    for i, x in enumerate(rows, 1):
        x['id'] = i
    return rows


# ------------------------------------------------------------------- FIT
def scan_fit(root, limit=None):
    """Vrátí ({'YYYY-MM-DD': balance}, {'YYYY-MM-DD': elevation_profile}, diag)."""
    zips = glob.glob(os.path.join(root, '**', 'UploadedFiles_*.zip'), recursive=True)
    tmp = None
    if zips:
        tmp = tempfile.mkdtemp(prefix='fit_')
        for z in zips:
            with zipfile.ZipFile(z) as zf:
                zf.extractall(tmp)
        files = glob.glob(os.path.join(tmp, '*.fit'))
    else:
        files = glob.glob(os.path.join(root, '**', '*.fit'), recursive=True)
    if limit:
        files = sorted(files, key=os.path.getsize, reverse=True)[:limit]

    bal, elevation = {}, {}
    declared, populated, parsed = 0, 0, 0
    for p in files:
        try:
            if HAVE_SDK:
                stream = Stream.from_file(p)
                msgs, _ = Decoder(stream).read()
                for s in msgs.get('session_mesgs', []):
                    if s.get('sport') != 'running':
                        continue
                    parsed += 1
                    day = str(s.get('start_time'))[:10]
                    if 'avg_stance_time_balance' in s:
                        declared += 1
                        v = s['avg_stance_time_balance']
                        if v is not None:
                            populated += 1
                            bal[day] = round(v, 2)
                    profile = fitreader._elevation_profile(msgs.get('record_mesgs', []))
                    if profile:
                        elevation[day] = profile
            elif HAVE_FALLBACK:
                rec = fitreader.running_dynamics(p)
                if not rec:
                    continue
                parsed += 1
                declared += 1
                if rec.get('gct_balance_l') is not None:
                    populated += 1
                    bal[rec['started_at']] = rec['gct_balance_l']
                if rec.get('elevation_profile'):
                    elevation[rec['started_at']] = rec['elevation_profile']
        except Exception:
            continue

    return bal, elevation, {
        'files_seen': len(files), 'runs_parsed': parsed,
        'balance_field_declared': declared, 'balance_field_populated': populated,
        'decoder': 'garmin-fit-sdk' if HAVE_SDK else ('fitreader (vestavěný)' if HAVE_FALLBACK else 'žádný'),
    }


# ------------------------------------------------------------------ report
METRIC_NEEDS = [
    ('Drift vertikálního poměru (TAVR)', ['vert_ratio_pct', 'stride_len_m']),
    ('Drift kontaktu se zemí', ['gct_ms', 'cadence_spm']),
    ('Posun symetrie kontaktu', ['gct_balance_l']),
    ('Rozpad techniky uvnitř běhu', ['vr_thirds']),
    ('EWMA poměr zátěže', ['distance_km']),
    ('Monotónnost a strain', ['distance_km']),
    ('Excentrická zátěž z klesání', ['descent_m']),
    ('Aerobní decoupling', ['hr_thirds', 'pace_thirds']),
]


def coverage(acts):
    cov = {}
    for f in ['distance_km', 'vert_ratio_pct', 'gct_ms', 'gct_balance_l', 'cadence_spm', 'stride_len_m',
              'descent_m', 'vr_thirds', 'hr_thirds', 'pace_thirds', 'rpe', 'feel_garmin']:
        n = sum(1 for a in acts if a.get(f) not in (None, 0))
        cov[f] = round(n / max(len(acts), 1) * 100)
    return cov


def build_seed(source, runner_id='run-user', name=None, do_fit=False, fit_limit=None, log=None):
    """Core of the CLI: turns a Garmin export (zip path or already-extracted
    folder) into the seed dict the platform consumes. Factored out of main()
    so the FastAPI upload endpoint (POST /api/integrations/garmin/import)
    can call the exact same code path as the command line — no separate,
    drifting reimplementation of the parsing logic.

    `log`, if given, is called with each progress line (main() passes
    `print`; the API endpoint can pass a no-op or a request-scoped logger).
    Raises ValueError if the export contains no runs.
    """
    def _log(msg):
        if log:
            log(msg)

    root = source
    tmp = None
    if os.path.isfile(root) and root.lower().endswith('.zip'):
        tmp = tempfile.mkdtemp(prefix='garmin_')
        with zipfile.ZipFile(root) as zf:
            zf.extractall(tmp)
        root = tmp

    try:
        _log('Čtu aktivity…')
        acts, meta = load_activities(root, runner_id)
        if not acts:
            raise ValueError('V exportu nejsou žádné běhy. Čekal jsem soubor *summarizedActivities.json.')
        _log(f'  {len(acts)} běhů z {meta.get("total_in_export")} aktivit celkem')

        _log('Čtu denní metriky…')
        daily = load_daily(root, runner_id)
        _log(f'  {len(daily)} dní')

        fitdiag = None
        if do_fit:
            _log('Procházím FIT soubory kvůli symetrii kontaktu a profilu nadmořské výšky…')
            bal, elevation, fitdiag = scan_fit(root, fit_limit)
            hit = elev_hit = 0
            for a in acts:
                if a['started_at'] in bal:
                    a['gct_balance_l'] = bal[a['started_at']]
                    hit += 1
                if a['started_at'] in elevation:
                    a['elevation_profile'] = elevation[a['started_at']]
                    elev_hit += 1
            _log(f'  dekodér: {fitdiag["decoder"]}, souborů {fitdiag["files_seen"]}, '
                 f'běhů {fitdiag["runs_parsed"]}, symetrie doplněna u {hit}, profil výšky u {elev_hit}')

        cov = coverage(acts)
        profile_name = name
        prof = glob.glob(os.path.join(root, '**', '*social-profile.json'), recursive=True)
        if prof and not profile_name:
            try:
                with open(prof[0], encoding='utf-8') as fh:
                    profile_name = json.load(fh).get('displayName') or json.load(open(prof[0]))\
                        .get('fullName')
            except Exception:
                pass

        seed = {
            '_meta': {
                'source': 'garmin_export', 'generated_at': datetime.now(timezone.utc).isoformat(),
                'activities': len(acts), 'daily': len(daily),
                'first_run': acts[0]['started_at'], 'last_run': acts[-1]['started_at'],
                'coverage_pct': cov, 'fit': fitdiag,
            },
            'runners': [{
                'id': runner_id, 'bib': '0001',
                'name': profile_name or 'Můj účet', 'city': None,
                'goal_race': None, 'goal_date': None,
                'prior_injury': None, 'prior_injury_months_ago': None,
                'device': 'Garmin', 'employer_id': None, 'partner_id': None,
            }],
            'activities': acts,
            'daily_metrics': daily,
            'activity_feedback': [
                {'id': i + 1, 'activity_id': a['id'], 'runner_id': runner_id,
                 'submitted_at': a['started_at'], 'feeling': a['feel_garmin'],
                 'legs': a['feel_garmin'], 'rpe': a['rpe'], 'pain_during': 0,
                 'pain_site': None, 'pain_points': [], 'niggle': False,
                 'note': 'Přeneseno z Garmin Connect (Feel / RPE).'}
                for i, a in enumerate([x for x in acts if x.get('feel_garmin')])
            ],
            'checkins': [],
        }
        return seed
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def print_coverage_report(seed):
    cov = seed['_meta']['coverage_pct']
    acts = seed['activities']
    print(f'Období: {acts[0]["started_at"]} → {acts[-1]["started_at"]}')
    print('\nPokrytí polí (% běhů):')
    for k, v in sorted(cov.items(), key=lambda x: -x[1]):
        print(f'  {k:18} {v:3d} %')
    print('\nCo z toho jde počítat:')
    for label, needs in METRIC_NEEDS:
        worst = min(cov.get(n, 0) for n in needs)
        mark = 'ano ' if worst >= 70 else ('částečně' if worst >= 30 else 'NE  ')
        print(f'  [{mark}] {label}  ({worst} % pokrytí)')
    if cov.get('gct_balance_l', 0) < 30:
        print('\nSymetrie kontaktu není k dispozici.')
        print('  Vertikální oscilaci, poměr a GCT hodinky měří ze zápěstí,')
        print('  ale symetrii kontaktu ne. Vyžaduje hrudní pás HRM-Pro / HRM-Run')
        print('  nebo Running Dynamics Pod. Bez nich zůstane pole prázdné i ve FIT.')
        print('  Platforma proto tento signál u takového účtu vůbec nezobrazí,')
        print('  místo aby ho tiše počítala z chybějících dat.')


def main():
    ap = argparse.ArgumentParser(description='Garmin export → schéma platformy Došlap')
    ap.add_argument('source', help='ZIP z Garmin Connect nebo rozbalená složka')
    ap.add_argument('-o', '--out', default='user_seed.json')
    ap.add_argument('--fit', action='store_true', help='projít i FIT soubory kvůli symetrii kontaktu')
    ap.add_argument('--fit-limit', type=int, default=None)
    ap.add_argument('--runner-id', default='run-user')
    ap.add_argument('--name', default=None)
    args = ap.parse_args()

    try:
        seed = build_seed(args.source, runner_id=args.runner_id, name=args.name,
                           do_fit=args.fit, fit_limit=args.fit_limit, log=print)
    except ValueError as e:
        sys.exit(str(e))

    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(seed, fh, ensure_ascii=False, indent=1)

    print(f'\nZapsáno: {args.out}')
    print_coverage_report(seed)


if __name__ == '__main__':
    main()
