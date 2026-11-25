"""Go Live end to end, against a running server and a local RTMP receiver (FFmpeg in listen mode), so nothing goes on the internet.

  NEONCLIPPING_URL=http://127.0.0.1:8799 GOLIVE_SOURCE=<source id> GOLIVE_LOGO=<image asset id> GOLIVE_BANNER=<image asset id> python tests/e2e_golive.py

Checks: 15 s test render in Shorts and Landscape (size, audio, logo and banner pixels), input validation, a real RTMP live
(goes "live", banner change shows up in the received stream), reconnect after the receiver drops, and stop.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

BASE = os.environ.get('NEONCLIPPING_URL', 'http://127.0.0.1:8770')
SOURCE = os.environ.get('GOLIVE_SOURCE', '')
LOGO = os.environ.get('GOLIVE_LOGO', '')
BANNER = os.environ.get('GOLIVE_BANNER', '')
DATA = Path(os.environ.get('GOLIVE_DATA', 'data'))
TMP = Path(tempfile.mkdtemp())
RTMP_PORT = 19350
FAILS = []


def check(name, ok, info=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f'  [{info}]' if info else ''))
    if not ok:
        FAILS.append(name)


def api(path, body=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def wait(lid, until, limit=120):
    t0 = time.time()
    s = {}
    while time.time() - t0 < limit:
        s = api('/golive/' + lid)[1]
        if s.get('status') in until:
            break
        time.sleep(.5)
    return s


def streams(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(path)], capture_output=True, text=True).stdout
    return json.loads(out or '{"streams":[]}')['streams']


def frame(path, t):
    out = TMP / f'f{time.time_ns()}.png'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(t), '-i', str(path), '-frames:v', '1', str(out)], check=True)
    return Image.open(out).convert('RGB')


def near(px, rgb, tol=70):
    return all(abs(a - b) <= tol for a, b in zip(px, rgb))


def receiver(out):
    return subprocess.Popen(['ffmpeg', '-v', 'error', '-listen', '1', '-i', f'rtmp://127.0.0.1:{RTMP_PORT}/live2/testkey',
                             '-c', 'copy', '-y', str(out)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


BASIC = {'id': SOURCE, 'cam': {'x': 0, 'y': 0, 'w': .3, 'h': .35}, 'game': {'x': .3, 'y': 0, 'w': .7, 'h': 1}, 'top': .32,
         'logo': LOGO, 'logo_pos': 'tr', 'logo_size': 20, 'banner_text': 'LIVE NOW · Follow @amanat__official_',
         'banner_pos': 'bottom', 'banner_bg': '#ff0000', 'banner_color': '#ffffff'}


def test_renders():
    cases = [('Shorts 9:16, face on top', {'format': 'shorts', 'layout': 'stack'}, (1080, 1920)),
             ('Landscape 16:9, facecam bottom-right + banner image', {'format': 'landscape', 'layout': 'pip_br', 'banner_image': BANNER, 'banner_pos': 'top', 'logo_pos': 'br'}, (1920, 1080))]
    for name, extra, size in cases:
        code, r = api('/golive/start', {**BASIC, **extra, 'test': True})
        check(f'{name}: test starts', code == 200, r if code != 200 else '')
        if code != 200:
            continue
        s = wait(r['live'], ('done', 'error', 'stopped'))
        check(f'{name}: test finishes', s.get('status') == 'done', f"{s.get('status')} {s.get('error') or ''} speed={s.get('speed')} encoder={s.get('encoder')}")
        if s.get('status') != 'done':
            continue
        path = DATA / (s['preview'].split('/')[-1] + '.mp4')
        st = streams(path)
        video = next((x for x in st if x['codec_type'] == 'video'), {})
        check(f'{name}: size {size[0]}x{size[1]}', (video.get('width'), video.get('height')) == size, f"{video.get('width')}x{video.get('height')}")
        check(f'{name}: has audio', any(x['codec_type'] == 'audio' for x in st))
        check(f'{name}: about 15 s long', 13 <= float(video.get('duration', 0)) <= 16, video.get('duration'))
        im = frame(path, 5)
        W, H = im.size
        px = lambda x, y: im.getpixel((int(x * W), int(y * H)))
        if extra['format'] == 'shorts':
            check(f'{name}: logo top-right', near(px(.86, .09), (0, 255, 0)), px(.86, .09))
            check(f'{name}: red banner at the bottom', near(px(.06, .80), (255, 0, 0)), px(.06, .80))
        else:
            check(f'{name}: banner image at the top', near(px(.5, .09), (255, 200, 0)), px(.5, .09))
            check(f'{name}: logo bottom-right', near(px(.89, .80), (0, 255, 0)), px(.89, .80))


def test_validation():
    code, r = api('/golive/start', {**BASIC, 'platform': 'youtube', 'key': ''})
    check('live without a stream key is refused', code == 400 and 'stream key' in r.get('detail', ''), r)
    code, r = api('/golive/start', {**BASIC, 'platform': 'custom', 'server': 'http://example.com', 'key': 'k'})
    check('non-RTMP server is refused', code == 400 and 'rtmp' in r.get('detail', ''), r)
    code, r = api('/golive/start', {**BASIC, 'test': True, 'format': 'tiktok'})
    check('unknown shape is refused', code == 400, r)
    code, r = api('/golive/start', {**BASIC, 'test': True, 'logo': 'nothere1'})
    check('missing logo is refused', code == 400 and 'logo' in r.get('detail', ''), r)


def test_bad_server():
    code, r = api('/golive/start', {**BASIC, 'format': 'shorts', 'layout': 'stack', 'platform': 'custom',
                                    'server': 'rtmp://127.0.0.1:19359/live2', 'key': 'secretkey123'})
    s = wait(r['live'], ('error', 'done', 'stopped'), 60) if code == 200 else {}
    check('unreachable server ends with a readable error', s.get('status') == 'error' and 'Could not connect' in (s.get('error') or ''), (s.get('error') or '')[:160])
    check('stream key never shown', 'secretkey123' not in json.dumps(s))


def test_live():
    first, second = TMP / 'live1.flv', TMP / 'live2.flv'
    rx = receiver(first)
    time.sleep(1)
    code, r = api('/golive/start', {**BASIC, 'format': 'shorts', 'layout': 'stack', 'platform': 'custom',
                                    'server': f'rtmp://127.0.0.1:{RTMP_PORT}/live2', 'key': 'testkey'})
    check('live starts', code == 200, r if code != 200 else '')
    if code != 200:
        rx.kill()
        return
    lid = r['live']
    s = wait(lid, ('live', 'error'), 40)
    check('goes live', s.get('status') == 'live', f"{s.get('status')} {s.get('error') or ''}")
    check('only one live at a time', api('/golive/start', {**BASIC, 'test': True})[0] == 409)
    time.sleep(2)
    a, t0 = api('/golive/' + lid)[1]['position'], time.time()
    time.sleep(5)
    b = api('/golive/' + lid)[1]['position']
    pace = (b - a) / (time.time() - t0)
    check('keeps real-time pace', .9 <= pace <= 1.1, f'{pace:.2f}x')
    code, u = api(f'/golive/{lid}/overlay', {'banner_bg': '#0000ff', 'banner_text': 'Changed while live'})
    check('banner can change while live', code == 200 and u['overlay']['banner_bg'] == '#0000ff', u if code != 200 else '')
    time.sleep(6)
    rx.terminate()                                         # the "internet" drops ...
    rx.wait(10)
    rx = receiver(second)                                  # ... and comes back
    s = wait(lid, ('reconnecting',), 30)
    check('notices the dropped connection', s.get('status') == 'reconnecting' or s.get('reconnects', 0) >= 1, s.get('status'))
    s = wait(lid, ('live', 'error'), 60)
    check('reconnects and is live again', s.get('status') == 'live' and s.get('reconnects', 0) >= 1, f"{s.get('status')} reconnects={s.get('reconnects')} {s.get('error') or ''}")
    time.sleep(4)
    check('stop', api(f'/golive/{lid}/stop', {})[0] == 200)
    s = wait(lid, ('stopped', 'error', 'done'), 20)
    check('ends as stopped', s.get('status') == 'stopped', s.get('status'))
    rx.wait(15)
    got = streams(first)
    check('receiver got a 9:16 stream with audio', any(x.get('height') == 1920 for x in got) and any(x['codec_type'] == 'audio' for x in got), [(x['codec_type'], x.get('width'), x.get('height')) for x in got])
    length = max(float(x.get('duration') or 0) for x in got) or float(subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(first)], capture_output=True, text=True).stdout or 0)
    early, late = frame(first, 3), frame(first, max(4, length - 1.5))
    W, H = early.size
    spot = (int(.06 * W), int(.80 * H))
    check('banner was red at the start', near(early.getpixel(spot), (255, 0, 0)), early.getpixel(spot))
    check('banner turned blue after the live change', near(late.getpixel(spot), (0, 0, 255)), late.getpixel(spot))
    check('stream after reconnect was received', bool(streams(second)))


class FakeYouTube:
    """Stands in for the connected channel: hands out the local receiver as the ingest address, then reports 'live'."""
    def __init__(self):
        self.calls, self.polls = [], 0

    def create_live(self, title, description, privacy, channel=None):
        self.calls.append(('create', title, privacy))
        return {'broadcast_id': 'B123', 'stream_id': 'S1', 'server': f'rtmp://127.0.0.1:{RTMP_PORT}/live2', 'key': 'testkey',
                'watch_url': 'https://www.youtube.com/watch?v=B123', 'studio_url': 'https://studio.youtube.com/video/B123/livestreaming'}

    def live_status(self, broadcast_id, channel=None):
        self.polls += 1
        return 'testing' if self.polls < 2 else 'live'

    def end_live(self, broadcast_id, channel=None):
        self.calls.append(('end', broadcast_id))


def test_youtube_auto():
    """The fully automatic path, in this process with a fake channel (the real API part is covered by tests/test_golive.py)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import golive

    def probe(path):
        s = streams(path)
        v = next(x for x in s if x['codec_type'] == 'video')
        return {'w': v['width'], 'h': v['height'], 'duration': float(v.get('duration') or 60)}
    fake = FakeYouTube()
    opts = golive.settings({**BASIC, 'platform': 'youtube_auto', 'title': 'Auto live test', 'privacy': 'unlisted', 'format': 'shorts', 'layout': 'stack'}, DATA)
    rx = receiver(TMP / 'auto.flv')
    time.sleep(1)
    live = golive.Live(DATA, probe, opts, '', DATA / (SOURCE + '.mp4'), {}, None, fake)
    live.start()
    t0 = time.time()
    while time.time() - t0 < 40 and live.status()['youtube'] != 'live':
        time.sleep(.5)
    s = live.status()
    check('auto: live created on the channel with title and privacy', fake.calls[:1] == [('create', 'Auto live test', 'unlisted')], fake.calls)
    check('auto: video is sent and YouTube reports live', s['status'] == 'live' and s['youtube'] == 'live', f"{s['status']} / {s['youtube']} / {s['stage']}")
    check('auto: watch link shown', s['watch_url'] == 'https://www.youtube.com/watch?v=B123')
    check('auto: stream key from YouTube never shown', 'testkey' not in json.dumps(s))
    time.sleep(3)
    live.stop()
    t0 = time.time()
    while time.time() - t0 < 15 and live.running():
        time.sleep(.3)
    time.sleep(.5)
    check('auto: Stop ends the live on YouTube too', ('end', 'B123') in fake.calls, fake.calls)
    rx.wait(10)
    check('auto: receiver got the stream', any(x.get('height') == 1920 for x in streams(TMP / 'auto.flv')))


if __name__ == '__main__':
    if not SOURCE:
        sys.exit('Set GOLIVE_SOURCE to the id of a video in the data folder.')
    test_validation()
    test_renders()
    test_bad_server()
    test_live()
    test_youtube_auto()
    print(('ALL PASSED' if not FAILS else f'{len(FAILS)} FAILED: ' + ', '.join(FAILS)))
    sys.exit(1 if FAILS else 0)
