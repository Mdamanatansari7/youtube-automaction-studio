"""Movie clipping: cut a whole movie (or any long video) into numbered Shorts, Part 1, Part 2, … in order.

1. Analyze (POST /movie/analyze): read the movie's length (and its YouTube captions, if any), fetch only its sound, and find
   the pauses in speech. Parts are about `part_len` seconds, but each cut moves back to the latest pause in its last few
   seconds, so nobody is cut off mid-sentence. The answer says how many parts the movie makes.
2. Make (POST /movie/make): for a link, fetch only each part's own seconds of video (a 2-hour movie is never downloaded whole
   up front), render each part 9:16 with the movie title and a PART n tag (and "PART n+1 NEXT →" at the end), save it in
   My clips, and optionally upload all parts to YouTube in order.
"""
import bisect
import json
import math
import re
import subprocess
import threading
import time
import uuid

from fastapi import HTTPException

PART_LENGTHS = (30, 45, 60, 90, 120, 180)
PAUSE_WINDOW = 10.0      # a cut may move up to this many seconds earlier to land in a pause
MIN_TAIL = 3.0           # a last piece shorter than this is dropped (usually silence or a logo)
MAX_PARTS = 400
LAYOUTS = ('blur', 'fill')
STYLES = ('gta', 'bold', 'clean', 'hormozi', 'mrbeast')
SILENCE = re.compile(r'silence_(start|end): (-?[0-9.]+)')
COLOR = re.compile(r'#[0-9a-fA-F]{6}')


# ---------------------------------------------------------------------------------------------------- planning the parts
def pauses(path, noise_db=-32, min_gap=.35):
    """Middle times (seconds) of the quiet gaps in a file's sound."""
    cmd = ['ffmpeg', '-hide_banner', '-nostats', '-v', 'info', '-i', str(path), '-vn',
           '-af', f'silencedetect=noise={noise_db}dB:d={min_gap}', '-f', 'null', '-']
    r = subprocess.run(cmd, capture_output=True, text=True)
    out, opened = [], None
    for kind, value in SILENCE.findall(r.stderr):
        t = float(value)
        if kind == 'start':
            opened = max(0.0, t)
        elif opened is not None:
            out.append(round((opened + t) / 2, 2))
            opened = None
    return out


def plan_parts(duration, part_len=60, start=0.0, end=None, quiet=(), window=PAUSE_WINDOW):
    """[(start, end), …] covering start..end in order. No part is longer than part_len; a part ends in a pause when there
    is one in its last `window` seconds (at most a third of the part)."""
    end = duration if end is None else min(end, duration)
    if not (math.isfinite(start) and math.isfinite(end)) or start < 0 or end - start < 1:
        raise ValueError('The part to cut is too short. Check “Start at” and “End at”.')
    window = min(window, part_len / 3)
    quiet = sorted(q for q in quiet if start < q < end)
    parts, t = [], float(start)
    while end - t > 1e-6:
        if end - t <= part_len:
            if end - t >= MIN_TAIL or not parts:
                parts.append((round(t, 2), round(end, 2)))
            break
        target = t + part_len
        i = bisect.bisect_right(quiet, target) - 1
        cut = quiet[i] if i >= 0 and quiet[i] >= target - window and quiet[i] > t + 1 else target
        parts.append((round(t, 2), round(cut, 2)))
        t = cut
        if len(parts) > MAX_PARTS:
            raise ValueError(f'This makes more than {MAX_PARTS} parts. Choose longer parts or a shorter range.')
    return parts


# ---------------------------------------------------------------------------------------------------- the PART tag
def series(body):
    """Validated title / PART tag settings of a movie part, or None for an ordinary clip. Raises ValueError."""
    s = body.get('series')
    if s is None:
        return None
    if not isinstance(s, dict):
        raise ValueError('Movie part settings must be an object.')
    try:
        part, total = int(s.get('part')), int(s.get('total') or 0)
    except (TypeError, ValueError):
        raise ValueError('The part number must be a whole number.')
    if not 1 <= part <= MAX_PARTS or not 0 <= total <= MAX_PARTS:
        raise ValueError('Part number out of range.')
    color = str(s.get('color') or '#db2777')
    if not COLOR.fullmatch(color):
        raise ValueError('Tag colour must look like #db2777.')

    def flag(key, default=True):
        value = s.get(key, default)
        return default if value is None else value is not False
    return {'part': part, 'total': total, 'title': str(s.get('title') or '')[:80], 'label': str(s.get('label') or 'PART')[:16],
            'color': color, 'show_title': flag('show_title'), 'show_part': flag('show_part'), 'show_total': flag('show_total', False),
            'next_hint': flag('next_hint')}


def _ass_color(hex_color):
    return ('&H00' + hex_color[5:7] + hex_color[3:5] + hex_color[1:3] + '&').upper()


def _box(w, h, r):
    """A rounded rectangle as an ASS drawing."""
    return (f'm {r} 0 l {w - r} 0 b {w} 0 {w} 0 {w} {r} l {w} {h - r} b {w} {h} {w} {h} {w - r} {h} '
            f'l {r} {h} b 0 {h} 0 {h} 0 {h - r} l 0 {r} b 0 0 0 0 {r} 0')


def label_band(layout, src_w, src_h, width, height):
    """y of the bottom edge of the space for the title and tag: just above the movie picture in the blurred layout,
    otherwise a fixed spot near the top over the picture."""
    if layout == 'blur' and src_w and src_h:
        top = (height - min(height, width * src_h / src_w)) / 2
        if top >= height * .12:
            return top
    return height * .22


def events(s, layout, src_w, src_h, width, height, duration):
    """ASS events: movie title + PART tag for the whole part, and “PART n+1 NEXT →” (or THE END) in its last seconds."""
    from captions import BS, stamp, safe, hook_lines
    sc = min(width / 1080, height / 1920)
    end = stamp(duration, True)
    out = []
    y = label_band(layout, src_w, src_h, width, height) - round(34 * sc)
    if s['show_part']:
        text = f"{s['label']} {s['part']}" + (f"/{s['total']}" if s['show_total'] and s['total'] else '')
        fs = round(58 * sc)
        bh, pad = round(84 * sc), round(30 * sc)
        bw = round(len(text) * fs * .62) + 2 * pad
        x, top = (width - bw) // 2, round(y - bh)
        out.append(f'Dialogue: 4,0:00:00.00,{end},Main,,0,0,0,,{{{BS}an7{BS}pos({x},{top}){BS}bord0{BS}shad0{BS}1c{_ass_color(s["color"])}{BS}p1}}{_box(bw, bh, round(20 * sc))}')
        out.append(f'Dialogue: 5,0:00:00.00,{end},Main,,0,0,0,,{{{BS}an5{BS}pos({width // 2},{top + bh // 2}){BS}fs{fs}{BS}b1{BS}c&H00FFFFFF&{BS}bord0{BS}shad0}}{safe(text.upper())}')
        y = top - round(22 * sc)
    if s['show_title'] and s['title'].strip():
        fs = round(64 * sc)
        lines = hook_lines(s['title'], width=max(12, int(width / (fs * .58))), max_lines=2)
        text = (BS + 'N').join(safe(line) for line in lines)
        out.append(f'Dialogue: 4,0:00:00.00,{end},Main,,0,0,0,,{{{BS}an2{BS}pos({width // 2},{round(y)}){BS}fs{fs}{BS}b1{BS}c&H00FFFFFF&{BS}3c&H00000000&{BS}bord4{BS}shad0}}{text}')
    if s['next_hint'] and duration >= 8:
        last = s['total'] and s['part'] >= s['total']
        hint = 'THE END' if last else f"{s['label']} {s['part'] + 1} NEXT →"
        a = stamp(max(0, duration - min(4, duration / 3)), True)
        fs = round(54 * sc)
        out.append(f'Dialogue: 6,{a},{end},Main,,0,0,0,,{{{BS}an5{BS}pos({width // 2},{round(height * .87)}){BS}fs{fs}{BS}b1{BS}c&H00FFFFFF&'
                   f'{BS}3c{_ass_color(s["color"])}{BS}bord6{BS}shad0{BS}fad(200,0)}}{safe(hint.upper())}')
    return out


def append(ass_path, s, layout, src_w, src_h, width, height, duration):
    """Add the title / PART tag to an ASS file written by captions.write()."""
    from pathlib import Path
    text = Path(ass_path).read_text(encoding='utf-8').rstrip('\n')
    Path(ass_path).write_text(text + '\n' + '\n'.join(events(s, layout, src_w, src_h, width, height, duration)) + '\n', encoding='utf-8')


# ---------------------------------------------------------------------------------------------------- web routes
def seconds(value, name):
    """'1:30', '0:01:30', '90' or 90 → 90.0; empty → None."""
    if value in (None, ''):
        return None
    bad = HTTPException(400, f'{name}: write the time like 1:30 or 0:01:30.')
    try:
        parts = [float(p) for p in str(value).strip().split(':')]
    except ValueError:
        raise bad
    if not 1 <= len(parts) <= 3 or any(not math.isfinite(p) or p < 0 for p in parts):
        raise bad
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def attach(app, DATA, state, probe, export, tools):
    """tools: 'yt' (yt-dlp with the app's options), 'section_start', 'dur' and 'pad' from app.py."""
    save, new_source = app.neon['save'], app.neon['new_source']
    stop = set()

    @app.post('/movie/analyze')
    def analyze(b: dict):
        url, src = new_source(b)
        try:
            part_len = int(b.get('part_len', 60))
        except (TypeError, ValueError):
            part_len = 0
        if part_len not in PART_LENGTHS:
            raise HTTPException(400, 'Choose a part length: ' + ', '.join(map(str, PART_LENGTHS)) + ' seconds.')
        start = seconds(b.get('start'), 'Start at') or 0.0
        end = seconds(b.get('end'), 'End at')
        if end is not None and end <= start + 1:
            raise HTTPException(400, '“End at” must be after “Start at”.')
        job = uuid.uuid4().hex
        save(job, {'id': job, 'kind': 'movie_analysis', 'status': 'running', 'stage': 'Reading the movie', 'progress': 0})

        def work():
            try:
                title, yt_words, audio = '', None, None
                if url:
                    with tools['yt']({'skip_download': True}) as y:
                        info = y.extract_info(url, download=False)
                    if info.get('is_live') or info.get('live_status') in ('is_live', 'is_upcoming'):
                        raise RuntimeError('This is a live stream. Use it after the stream has ended.')
                    title = str(info.get('title') or '')
                    duration = float(info.get('duration') or 0)
                    if duration < 5:
                        raise RuntimeError('Could not read how long this video is.')
                    try:
                        from captions_yt import from_info
                        yt_words = from_info(info)
                    except Exception:                                   # noqa: BLE001
                        yt_words = None
                    save(job, {'title': title, 'duration': duration, 'thumbnail': info.get('thumbnail'),
                               'stage': 'Fetching only the sound to find the pauses', 'progress': .05})

                    def hook(d):
                        total = d.get('total_bytes') or d.get('total_bytes_estimate')
                        if total and d.get('status') == 'downloading':
                            save(job, {'stage': f"Fetching the sound {d['downloaded_bytes'] / 1048576:.0f}/{total / 1048576:.0f} MB",
                                       'progress': .05 + .6 * d['downloaded_bytes'] / total})
                    with tools['yt']({'format': 'ba[ext=m4a]/ba/worst', 'outtmpl': str(DATA / (job + '.audio.%(ext)s')),
                                      'progress_hooks': [hook]}) as y:
                        y.download([url])
                    audio = next(f for f in DATA.glob(job + '.audio.*') if f.suffix not in ('.part', '.ytdl'))
                    if yt_words:
                        (DATA / (job + '.words.json')).write_text(json.dumps(yt_words), encoding='utf-8')
                else:
                    duration = probe(src)['duration']
                    audio = src
                    title = str(b.get('title') or '').strip()
                    save(job, {'title': title, 'duration': duration})
                save(job, {'stage': 'Finding pauses in speech, so no sentence is cut in half', 'progress': .7})
                quiet = pauses(audio)
                parts = plan_parts(duration, part_len, start, end, quiet)
                save(job, {'status': 'done', 'progress': 1, 'stage': f'{len(parts)} parts of about {part_len} seconds',
                           'part_len': part_len, 'parts': [{'n': i + 1, 'start': a, 'end': z} for i, (a, z) in enumerate(parts)],
                           'count': len(parts), 'pauses': len(quiet), 'source': {'url': url, 'id': '' if url else src.stem},
                           'audio': audio.name if url else '', 'captions': 'YouTube captions' if yt_words else 'speech model'})
            except Exception as e:                                      # noqa: BLE001
                save(job, {'status': 'error', 'error': str(e)[-500:]})
        threading.Thread(target=work, daemon=True).start()
        return {'job': job}

    @app.get('/movie/{job}')
    def movie_status(job: str):
        row = state.get(job)
        if not row or row.get('kind') not in ('movie_analysis', 'movie_make'):
            raise HTTPException(404, 'Not found (the app was restarted). Analyze the movie again.')
        return row

    @app.post('/movie/make')
    def make(b: dict):
        aid = str(b.get('analysis') or '')
        a = state.get(aid) or {}
        if a.get('kind') != 'movie_analysis' or a.get('status') != 'done':
            raise HTTPException(400, 'Analyze the movie first.')
        wanted = b.get('parts')
        if wanted is None:
            parts = list(a['parts'])
        else:
            if not isinstance(wanted, list) or not wanted:
                raise HTTPException(400, 'Choose at least one part.')
            try:
                pick = {int(n) for n in wanted}
            except (TypeError, ValueError):
                raise HTTPException(400, 'Parts must be numbers.')
            parts = [p for p in a['parts'] if p['n'] in pick]
            if not parts:
                raise HTTPException(400, 'Choose at least one part.')
        title = str(b.get('title') or a.get('title') or 'Movie').strip()[:80] or 'Movie'
        layout = b.get('layout', 'blur')
        style = b.get('caption_style', 'gta')
        language = b.get('language') or None
        import languages
        if layout not in LAYOUTS:
            raise HTTPException(400, 'Choose “Full movie + blurred background” or “Crop to fill”.')
        if style not in STYLES:
            raise HTTPException(400, 'Choose a valid caption style.')
        if not languages.valid(language):
            raise HTTPException(400, 'Choose Auto, Hinglish or a language from the list.')
        tag = {'title': title, 'total': a['count'], 'color': b.get('color') or '#db2777', 'label': b.get('label') or 'PART',
               **{k: b[k] for k in ('show_title', 'show_part', 'show_total', 'next_hint') if k in b}}
        try:
            series({'series': {**tag, 'part': 1}})
        except ValueError as e:
            raise HTTPException(400, str(e))
        upload = bool(b.get('upload'))
        if upload:
            ytm = getattr(app.state, 'yt_manager', None)
            if not ytm:
                raise HTTPException(400, 'YouTube is not available.')
            try:
                ytm._upload_channel(b.get('channel') or None)
            except RuntimeError as e:
                raise HTTPException(400, str(e))
        from standalone import source_height
        height = source_height(b.get('source_height'))
        job = uuid.uuid4().hex
        save(job, {'id': job, 'kind': 'movie_make', 'status': 'running', 'stage': 'Starting', 'progress': 0, 'clips': [],
                   'title': title, 'analysis': aid, 'total': len(parts)})

        def work():
            from concurrent.futures import ThreadPoolExecutor
            url, sid = a['source']['url'], a['source']['id']
            audio = DATA / a['audio'] if a.get('audio') else None
            words_file = DATA / (aid + '.words.json')
            yt_words = json.loads(words_file.read_text(encoding='utf-8')) if words_file.exists() else None
            clips, pool, futures = [], None, {}
            try:
                if url:
                    from standalone import source_format
                    from yt_dlp.utils import download_range_func

                    def fetch(p):
                        name = uuid.uuid4().hex
                        for attempt in range(3):
                            if job in stop:
                                return None
                            try:
                                with tools['yt']({'format': source_format(height), 'merge_output_format': 'mp4',
                                                  'outtmpl': str(DATA / (name + '.%(ext)s')),
                                                  'download_ranges': download_range_func(None, [(max(0, p['start'] - tools['pad']), p['end'] + 1)])}) as y:
                                    y.download([url])
                                return name
                            except Exception:                           # noqa: BLE001
                                if attempt == 2:
                                    raise
                                time.sleep(3 * (attempt + 1))
                    pool = ThreadPoolExecutor(max_workers=3)
                    futures = {p['n']: pool.submit(fetch, p) for p in parts}
                for i, p in enumerate(parts):
                    if job in stop:
                        save(job, {'status': 'stopped', 'stage': f'Stopped after {len(clips)} parts'})
                        return
                    n = p['n']
                    save(job, {'stage': f'Part {n}: ' + ('fetching its video' if url else 'rendering'), 'progress': i / len(parts)})
                    entry = {'n': n, 'start': p['start'], 'end': p['end'], 'title': f'{title} Part {n}'}
                    try:
                        if url:
                            name = futures[n].result()
                            if not name:
                                continue
                            f = DATA / (name + '.mp4')
                            guess = max(0, p['start'] - tools['pad'])
                            real = tools['section_start'](audio, f, guess) if audio else guess
                            s0 = max(0.0, p['start'] - real)
                            e0 = min(tools['dur'](f), s0 + p['end'] - p['start'])
                            src_id = name
                        else:
                            src_id, s0, e0 = sid, p['start'], p['end']
                        save(job, {'stage': f'Part {n}: rendering 9:16 with the PART tag'})
                        body = {'id': src_id, 'start': round(s0, 3), 'end': round(e0, 3), 'layout': layout, 'top': .32,
                                'captions': b.get('captions', True) is not False, 'caption_style': style, 'language': language,
                                'caption_y': 1450, 'caption_anim': 'highlight', 'hook': '', 'hook_enabled': False,
                                'aspect': 'vertical', 'resolution': 1080, 'fps': 0, 'title': entry['title'], 'post_caption': entry['title'],
                                'cam': {'x': 0, 'y': 0, 'w': .25, 'h': .3}, 'game': {'x': 0, 'y': 0, 'w': 1, 'h': 1},
                                'batch_id': job, 'source_url': url, 'series': {**tag, 'part': n}}
                        if body['captions'] and yt_words:
                            from captions_yt import window
                            limit = e0 - s0
                            body['words'] = [w for w in window(yt_words, p['start'], p['end']) if 0 <= w['start'] < w['end'] <= limit]
                        ej = export(body)['job']
                        while state.get(ej, {}).get('status') == 'running':
                            time.sleep(.7)
                        r = state.get(ej, {})
                        entry.update(file=ej, error=r.get('error'))
                    except HTTPException as e:
                        entry['error'] = str(e.detail)
                    except Exception as e:                              # noqa: BLE001
                        entry['error'] = str(e)[-300:]
                    clips.append(entry)
                    save(job, {'clips': list(clips), 'stage': f'Part {n} ready ({i + 1}/{len(parts)})', 'progress': (i + 1) / len(parts)})
                done = {'status': 'done', 'stage': f'{sum(1 for c in clips if not c.get("error"))} of {len(parts)} parts ready', 'progress': 1}
                if upload:
                    try:
                        done['uploads'] = queue_upload(clips, title, a['count'], b.get('privacy'), b.get('channel'))
                    except Exception as e:                              # noqa: BLE001
                        done['upload_error'] = str(e)[-300:]
                save(job, done)
            except Exception as e:                                      # noqa: BLE001
                save(job, {'status': 'error', 'error': str(e)[-500:], 'clips': list(clips)})
            finally:
                if pool:
                    pool.shutdown(wait=False, cancel_futures=True)
        threading.Thread(target=work, daemon=True).start()
        return {'job': job}

    def queue_upload(clips, title, total, privacy=None, channel=None):
        """Upload finished parts one after another in part order (Part 1 first)."""
        ytm = app.state.yt_manager
        cfg = ytm.get_config()
        ready = sorted((c for c in clips if c.get('file') and not c.get('error')), key=lambda c: c['n'])
        if not ready:
            raise RuntimeError('No finished parts to upload.')
        items = [{'clip_id': c['file'], 'title': f"{title} Part {c['n']} #Shorts"[:100],
                  'description': f"{title} · Part {c['n']}" + (f' of {total}' if total else '') +
                                 '\n\nWatch every part in order on this channel.\n#Shorts #Movie'} for c in ready]
        tags = [title[:30], 'Shorts', 'Movie', 'Movie clips', 'Movie parts']
        privacy = privacy if privacy in ('public', 'unlisted', 'private') else cfg.get('default_privacy', 'public')
        return ytm.start_batch(items, privacy, tags, '', channel=channel or None)

    @app.post('/movie/{job}/stop')
    def movie_stop(job: str):
        if (state.get(job) or {}).get('kind') != 'movie_make':
            raise HTTPException(404, 'Not found.')
        stop.add(job)
        return {'ok': True}

    @app.post('/movie/{job}/upload')
    def movie_upload(job: str, b: dict = None):
        row = state.get(job) or {}
        if row.get('kind') != 'movie_make':
            raise HTTPException(404, 'Not found (the app was restarted). Upload from My clips instead.')
        if not getattr(app.state, 'yt_manager', None):
            raise HTTPException(400, 'YouTube is not available.')
        b = b or {}
        a = state.get(row.get('analysis')) or {}
        try:
            jobs = queue_upload(row.get('clips') or [], row.get('title') or 'Movie', a.get('count') or 0, b.get('privacy'), b.get('channel'))
        except RuntimeError as e:
            raise HTTPException(400, str(e))
        return {'ok': True, 'jobs': jobs}
