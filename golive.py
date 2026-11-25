"""Go Live: stream a video (a link, or the source loaded in step 01) to YouTube Live, Facebook, Twitch or any RTMP server,
as a 9:16 Shorts live or a 16:9 landscape live, with the same layouts and facecam boxes as Shorts, plus your logo and banner.

The logo and banner are drawn by Pillow into one transparent layer that is fed to FFmpeg through a pipe a few times a second,
so they can be changed while the stream is on (this FFmpeg has no drawtext, and a looped image file is read only once).
A dropped connection is retried and the stream resumes where it was. The stream key never appears in the status, the log or errors.
One live (or one 15 s test) at a time. Phones reach /golive only after pairing with the PIN (phone.py).
"""
import io
import json
import math
import os
import re
import subprocess
import threading
import time
import uuid
from collections import deque

from fastapi import HTTPException

import encoders
import styling
from layouts import CATALOG, output_settings, render_graph

PLATFORMS = {
    'youtube_auto': ('your YouTube channel', ''),            # the app creates the live itself on the connected channel: no stream key
    'youtube': ('YouTube Live', 'rtmp://a.rtmp.youtube.com/live2'),
    'facebook': ('Facebook Live', 'rtmps://live-api-s.facebook.com:443/rtmp'),
    'twitch': ('Twitch', 'rtmp://live.twitch.tv/app'),
    'custom': ('Custom RTMP', ''),
}
FORMATS = {'shorts': 'vertical', 'landscape': 'landscape'}
LANDSCAPE_LAYOUTS = ('blur', 'fill', 'game', 'pip_tl', 'pip_tr', 'pip_bl', 'pip_br', 'side')
FACE_LAYOUTS = ('stack', 'bottom', 'pip_tl', 'pip_tr', 'pip_bl', 'pip_br', 'circle', 'side')   # layouts that show the facecam box
CORNERS = ('tl', 'tr', 'bl', 'br')
BANNER_POS = ('top', 'bottom')
LAYER_FPS = 4          # how often the logo/banner layer is refreshed in a live (changes show within ~1.5 s)
TEST_SECONDS = 15
RETRIES = 5            # reconnect attempts after the connection drops
SERVER = re.compile(r'^rtmps?://[^\s/]+(/[^\s]*)?$')
PREVIEW = re.compile(r'^golive[0-9a-f]{16}\.mp4$')      # a 15 s test preview (a downloaded source is golive…dl.mp4)
FONTS = ('/System/Library/Fonts/Supplemental/Arial Bold.ttf', '/Library/Fonts/Arial Bold.ttf', 'C:/Windows/Fonts/arialbd.ttf',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf')


def _number(value, low, high, name):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be a number.')
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be between {low:g} and {high:g}.')
    return value


def _rect(value, default):
    r = value if isinstance(value, dict) else default
    try:
        out = {k: float(r[k]) for k in ('x', 'y', 'w', 'h')}
    except (KeyError, TypeError, ValueError):
        raise ValueError('Check the facecam and gameplay boxes.')
    if not all(map(math.isfinite, out.values())) or min(out.values()) < 0 or out['w'] < .01 or out['h'] < .01:
        raise ValueError('Check the facecam and gameplay boxes.')
    return out


def overlay_settings(b, data, old=None):
    """Logo + banner options, validated. Missing keys keep their old value, so the live panel can change one thing at a time."""
    o = dict(old or {})

    def pick(key, allowed, default):
        value = b.get(key, o.get(key, default))
        if value not in allowed:
            raise ValueError(f'Choose a valid {key.replace("_", " ")}.')
        return value

    for key, label in (('logo', 'logo image'), ('banner_image', 'banner image')):
        value = b.get(key, o.get(key)) or None
        if value and not styling.asset_path(data, value, 'image'):
            raise ValueError(f'The {label} was not found. Upload it again.')
        o[key] = value
    o['logo_pos'] = pick('logo_pos', CORNERS, 'tr')
    o['logo_size'] = _number(b.get('logo_size', o.get('logo_size', 18)), 5, 40, 'Logo size')
    o['logo_opacity'] = _number(b.get('logo_opacity', o.get('logo_opacity', 100)), 10, 100, 'Logo opacity')
    o['banner_text'] = ' '.join(str(b.get('banner_text', o.get('banner_text', '')) or '').split())[:120]
    o['banner_pos'] = pick('banner_pos', BANNER_POS, 'bottom')
    o['banner_color'] = styling.hexcolor(b.get('banner_color', o.get('banner_color')), '#ffffff')
    o['banner_bg'] = styling.hexcolor(b.get('banner_bg', o.get('banner_bg')), '#ff4ba5')
    o['show_logo'] = b.get('show_logo', o.get('show_logo', True)) is not False
    o['show_banner'] = b.get('show_banner', o.get('show_banner', True)) is not False
    return o


def _font(size):
    from PIL import ImageFont
    for path in FONTS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return ImageFont.load_default(size=size)


def _wrap(draw, text, font, width, lines=2):
    words, out = text.split(), ['']
    for word in words:
        trial = (out[-1] + ' ' + word).strip()
        if draw.textlength(trial, font=font) <= width or not out[-1]:
            out[-1] = trial
        elif len(out) < lines:
            out.append(word)
        else:
            return None
    return out if all(draw.textlength(line, font=font) <= width for line in out) else None


def render_layer(o, width, height, data):
    """The transparent logo + banner layer as a PIL image, or None when there is nothing to draw."""
    from PIL import Image, ImageDraw
    layer = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    vertical = height > width
    margin = round(min(width, height) * .04)
    top_safe = round(height * .05)
    bottom_safe = round(height * (.17 if vertical else .06))      # the YouTube buttons cover the bottom of a Shorts live
    drew = False
    banner_box = None
    if o.get('show_banner') and (o.get('banner_text') or o.get('banner_image')):
        bw = width - 2 * margin
        parts = []
        if o.get('banner_image'):
            p = styling.asset_path(data, o['banner_image'], 'image')
            if p:
                img = Image.open(p).convert('RGBA')
                h = max(1, round(img.height * bw / img.width))
                if h > height * .22:
                    h = round(height * .22)
                img = img.resize((bw, h), Image.LANCZOS)
                parts.append(img)
        if o.get('banner_text'):
            probe = ImageDraw.Draw(layer)
            pad = round(min(width, height) * .025)
            size = round(min(width, height) * .062)
            while True:
                font = _font(size)
                lines = _wrap(probe, o['banner_text'], font, bw - 2 * pad)
                if lines or size <= 18:
                    break
                size -= 2
            lines = lines or [o['banner_text']]
            line_h = round(size * 1.22)
            strip = Image.new('RGBA', (bw, line_h * len(lines) + 2 * pad), (0, 0, 0, 0))
            d = ImageDraw.Draw(strip)
            r, g, b = (int(o['banner_bg'][i:i + 2], 16) for i in (1, 3, 5))
            d.rounded_rectangle((0, 0, bw - 1, strip.height - 1), radius=round(pad * 1.2), fill=(r, g, b, 235))
            for i, line in enumerate(lines):
                tw = d.textlength(line, font=font)
                d.text(((bw - tw) / 2, pad + i * line_h), line, font=font, fill=o['banner_color'])
            parts.append(strip)
        if parts:
            gap = round(margin / 3)
            box_h = sum(p.height for p in parts) + gap * (len(parts) - 1)
            y = top_safe if o['banner_pos'] == 'top' else height - bottom_safe - box_h
            banner_box = (y, y + box_h)
            for part in parts:
                layer.alpha_composite(part, (margin, y))
                y += part.height + gap
            drew = True
    if o.get('show_logo') and o.get('logo'):
        p = styling.asset_path(data, o['logo'], 'image')
        if p:
            logo = Image.open(p).convert('RGBA')
            w = max(1, round(width * o['logo_size'] / 100))
            h = max(1, round(logo.height * w / logo.width))
            if h > height * .3:
                h = round(height * .3)
                w = max(1, round(logo.width * h / logo.height))
            logo = logo.resize((w, h), Image.LANCZOS)
            if o['logo_opacity'] < 100:
                logo.putalpha(logo.getchannel('A').point(lambda a: int(a * o['logo_opacity'] / 100)))
            x = margin if o['logo_pos'] in ('tl', 'bl') else width - w - margin
            top_corner = o['logo_pos'] in ('tl', 'tr')
            y = top_safe if top_corner else height - h - bottom_safe
            if banner_box and top_corner and o['banner_pos'] == 'top':
                y = banner_box[1] + round(margin / 2)          # never on top of the banner
            if banner_box and not top_corner and o['banner_pos'] == 'bottom':
                y = banner_box[0] - h - round(margin / 2)
            layer.alpha_composite(logo, (x, max(0, y)))
            drew = True
    return layer if drew else None


def _png(image, width, height):
    from PIL import Image
    buf = io.BytesIO()
    (image or Image.new('RGBA', (width, height), (0, 0, 0, 0))).save(buf, 'PNG', compress_level=1)
    return buf.getvalue()


def video_encoder(bitrate_k, fps, hardware=True):
    """Constant-bitrate H.264 for streaming: NVENC or VideoToolbox when they work here, otherwise x264 (always works)."""
    rate, buf, gop = f'{bitrate_k}k', f'{bitrate_k * 2}k', str(fps * 2)
    common = ['-b:v', rate, '-maxrate', rate, '-bufsize', buf, '-g', gop, '-pix_fmt', 'yuv420p']
    name = encoders.h264()[0][1] if hardware else 'libx264'
    if name == 'h264_nvenc':
        return ['-c:v', 'h264_nvenc', '-preset', 'p4', '-tune', 'll', '-rc', 'cbr', *common]
    if name == 'h264_videotoolbox':
        return ['-c:v', 'h264_videotoolbox', '-realtime', '1', '-allow_sw', '1', '-profile:v', 'high', *common]
    if name == 'h264_mediacodec':                     # the phone's hardware encoder: cool and light enough for a 24 h live
        return [*encoders.MEDIACODEC, '-b:v', rate, '-maxrate', rate, '-bufsize', buf, '-g', gop, '-bitrate_mode', '2']
    return ['-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'zerolatency', '-profile:v', 'high', *common,
            '-keyint_min', gop, '-sc_threshold', '0']


def crop_window(src_w, src_h, out_w, out_h, position=.5):
    """The biggest part of the source with the output's shape. position slides it: 0 = left (or top), .5 = centre, 1 = right (or bottom)."""
    position = min(1.0, max(0.0, float(position)))
    if src_w * out_h > src_h * out_w:                     # source is wider than the output: cut the sides
        cw = max(2, int(src_h * out_w / out_h) // 2 * 2)
        return (int((src_w - cw) * position), 0, cw, src_h)
    ch = max(2, int(src_w * out_h / out_w) // 2 * 2)      # source is taller: cut top and bottom
    return (0, int((src_h - ch) * position), src_w, ch)


def settings(b, data):
    """Everything about a live except its source, validated. Raises ValueError with a readable message."""
    fmt = b.get('format', 'shorts')
    if fmt not in FORMATS:
        raise ValueError('Choose Shorts (9:16) or Landscape (16:9).')
    quality = int(_number(b.get('quality', 1080), 720, 1080, 'Quality'))
    fps = int(_number(b.get('fps', 30), 30, 60, 'Frame rate'))
    if quality not in (720, 1080) or fps not in (30, 60):
        raise ValueError('Choose 720p or 1080p at 30 or 60 fps.')
    width, height, _ = output_settings({'aspect': FORMATS[fmt], 'resolution': quality})
    layout = b.get('layout') or ('fill' if fmt == 'shorts' else 'blur')      # a Shorts live fills the tall screen by cropping
    if layout not in {x[0] for x in CATALOG}:
        raise ValueError('Choose a valid layout.')
    if fmt == 'landscape' and layout not in LANDSCAPE_LAYOUTS:
        layout = 'blur'                                         # face-above-game layouts only make sense standing up
    top = _number(b.get('top', .32), .2, .5, 'Face size')
    custom_cam = b.get('custom_cam') or None
    if custom_cam and not styling.asset_path(data, custom_cam, 'video'):
        raise ValueError('Your facecam video was not found. Upload it again.')
    test = b.get('test') is True
    platform = b.get('platform', 'youtube_auto')
    if platform not in PLATFORMS:
        raise ValueError('Choose where to go live.')
    server = (str(b.get('server') or '').strip() if platform == 'custom' else PLATFORMS[platform][1]).rstrip('/')
    key = '' if platform == 'youtube_auto' else str(b.get('key') or '').strip()
    privacy = b.get('privacy', 'public')
    if privacy not in ('public', 'unlisted', 'private'):
        raise ValueError('Choose Public, Unlisted or Private.')
    if not test and platform != 'youtube_auto':
        if not SERVER.match(server):
            raise ValueError('The server must start with rtmp:// or rtmps://')
        if (not key and platform != 'custom') or len(key) > 300 or re.search(r'\s', key):
            raise ValueError('Paste the stream key (YouTube Studio → Go live → Stream → Stream key).')
    bitrate = (6000 if quality == 1080 else 3500) * (3 if fps == 60 else 2) // 2
    return {'format': fmt, 'width': width, 'height': height, 'fps': fps, 'quality': quality, 'bitrate': bitrate,
            'layout': layout, 'top': top, 'crop': _number(b.get('crop', 50), 0, 100, 'Crop position') / 100,
            'cam_auto': b.get('cam_auto') is True,               # find the facecam in this video instead of using the drawn boxes
            'cam': _rect(b.get('cam'), {'x': 0, 'y': 0, 'w': .25, 'h': .3}),
            'game': _rect(b.get('game'), {'x': .25, 'y': 0, 'w': .75, 'h': 1}), 'custom_cam': custom_cam,
            'loop': b.get('loop', True) is not False, 'test': test, 'platform': platform,
            'url': (server + '/' + key) if key else server, 'key': key, 'privacy': privacy,
            'title': ' '.join(str(b.get('title') or '').split())[:100] or 'LIVE',
            'channel': str(b.get('channel') or '') or None,      # which connected YouTube channel (default: the active one)
            'description': str(b.get('description') or '')[:4900],
            'overlay': overlay_settings(b, data)}


def friendly(error, platform):
    """A readable message for the usual FFmpeg/RTMP failures."""
    text = error.lower()
    where = PLATFORMS.get(platform, ('the server',))[0]
    if any(k in text for k in ('connection refused', 'input/output error', 'server returned 4', 'broken pipe', 'end of file',
                               'error opening output', 'connection reset', 'timed out', 'failed to resolve', 'handshake')):
        if platform == 'youtube_auto':
            return f'Could not send the video to YouTube. Check your internet and try again. Details: {error[-200:]}'
        return (f'Could not connect to {where}. Check the stream key, your internet, and that a live stream is set up '
                f'(YouTube Studio → Go live → Stream). Details: {error[-200:]}')
    return error[-400:] or 'FFmpeg stopped unexpectedly.'


class Live:
    def __init__(self, data, probe, opts, url, source, app_state, download, youtube=None):
        self.id = 'golive' + uuid.uuid4().hex[:16]
        self.data, self.probe, self.o, self.link, self.src = data, probe, opts, url, source
        self.app_state, self.download, self.youtube = app_state, download, youtube
        self.broadcast = None                   # the live made on the connected YouTube channel (youtube_auto)
        self.stop_flag = threading.Event()
        self.proc = None
        self.lock = threading.Lock()
        self.errors = deque(maxlen=25)
        self.layer = b''
        self.dl_job = None
        self.started = self.ended = None       # wall clock of the first frame on air / the end
        self.ever_live = False
        self.state = {'id': self.id, 'status': 'starting', 'stage': 'Preparing', 'test': opts['test'], 'format': opts['format'],
                      'destination': 'Test run (nothing goes live)' if opts['test'] else PLATFORMS[opts['platform']][0],
                      'size': f"{opts['width']}x{opts['height']}", 'fps_target': opts['fps'], 'bitrate_target': f"{opts['bitrate']} kbps",
                      'layout': opts['layout'], 'source': url or 'Loaded video', 'elapsed': 0, 'position': 0, 'duration': 0,
                      'fps': 0, 'bitrate': '', 'speed': '', 'dropped': 0, 'reconnects': 0, 'encoder': '', 'error': None,
                      'preview': None, 'overlay': opts['overlay'], 'youtube': '', 'watch_url': None, 'studio_url': None, 'facecam': '',
                      'privacy': opts['privacy'] if opts['platform'] == 'youtube_auto' else None}

    # ---------- public
    def running(self):
        return self.state['status'] in ('starting', 'downloading', 'connecting', 'live', 'reconnecting', 'testing')

    def status(self):
        s = dict(self.state)
        if s['status'] == 'downloading' and self.dl_job:
            s['stage'] = (self.app_state.get(self.dl_job) or {}).get('stage') or s['stage']
        if self.started:
            s['elapsed'] = int((self.ended or time.time()) - self.started)
        return s

    def update_overlay(self, b):
        self.o['overlay'] = overlay_settings(b, self.data, self.o['overlay'])
        self._render()
        self.state['overlay'] = self.o['overlay']
        return self.status()

    def stop(self):
        self.stop_flag.set()
        p = self.proc
        if p and p.poll() is None:
            self.state['stage'] = 'Stopping…'

            def end():
                try:
                    p.stdin.close()                             # end the logo/banner pipe first, or FFmpeg keeps waiting on it
                except (OSError, ValueError):
                    pass
                p.terminate()
                try:
                    p.wait(1)                                   # while reading the pipe FFmpeg often ignores SIGTERM; an RTMP stream needs no tidy end
                except subprocess.TimeoutExpired:
                    p.kill()
                m = getattr(self, 'mux', None)                  # the phone's second FFmpeg (MPEG-TS -> RTMP)
                if m and m.poll() is None:
                    m.terminate()
            threading.Thread(target=end, daemon=True).start()
        if self.state['status'] in ('starting', 'downloading'):
            self.state.update(status='stopped', stage='Stopped before going live')

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    # ---------- inside
    def _set(self, **fields):
        self.state.update(fields)

    def _redact(self, text):
        return text.replace(self.o['key'], '••••') if self.o['key'] else text

    def _render(self):
        W, H = self.o['width'], self.o['height']
        image = render_layer(self.o['overlay'], W, H, self.data)
        self.has_graphics = image is not None
        self.layer = _png(image, W, H)
        if self.o['test'] and image is not None:
            self.layer_file.write_bytes(self.layer)

    def _source(self):
        if self.src is not None:
            return self.src
        self._set(status='downloading', stage='Downloading the video…')
        self.dl_job = self.id + 'dl'
        self.app_state[self.dl_job] = {'status': 'running', 'stage': 'Checking video length…'}
        try:
            _, path = self.download(self.link, self.dl_job, 1080)
        finally:
            self.app_state.pop(self.dl_job, None)
        return path

    def _has_audio(self, path):
        r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0', str(path)],
                           capture_output=True, text=True)
        return bool(r.stdout.strip())

    def _command(self, start_at, encoder):
        o = self.o
        live = not o['test']
        ts = encoders.via_ts(encoder)        # phone hardware encoder: write MPEG-TS, a second FFmpeg sends it as FLV (see _mux_command)
        cmd = ['ffmpeg', '-hide_banner', '-v', 'error', '-nostats', *([] if live and ts else ['-progress', 'pipe:1']), '-y']
        cmd += (['-re'] if live else []) + (['-stream_loop', '-1'] if live and o['loop'] else [])
        cmd += (['-ss', f'{start_at:.2f}'] if start_at > 0 else []) + ['-i', str(self.src)]
        index = 1
        cam_input = None
        if self.cam_file:
            cmd += ['-stream_loop', '-1', '-i', str(self.cam_file)]
            cam_input, index = f'[{index}:v]', index + 1
        layer_index = None
        if live:
            cmd += ['-re', '-probesize', '32', '-analyzeduration', '0',      # (no -thread_queue_size: newer FFmpeg builds refuse it on inputs)
                    '-f', 'image2pipe', '-framerate', str(LAYER_FPS), '-i', 'pipe:0']
            layer_index, index = index, index + 1
        elif self.has_graphics:
            cmd += ['-loop', '1', '-framerate', str(LAYER_FPS), '-i', str(self.layer_file)]
            layer_index, index = index, index + 1
        audio = '0:a:0'
        if not self.audio:
            cmd += ['-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo']
            audio, index = f'{index}:a', index + 1
        graph = render_graph(o['layout'], self.rects, o['top'], o['width'], o['height'], '',
                             custom_cam=bool(cam_input), cam_input=cam_input or '[1:v]')
        graph += f";[base]fps={o['fps']},format=yuv420p[vb]"
        graph += (f';[vb][{layer_index}:v]overlay=0:0:eof_action=repeat,format=yuv420p[v]' if layer_index is not None else ';[vb]null[v]')
        cmd += ['-filter_complex', graph, '-map', '[v]', '-map', audio, *encoder, '-r', str(o['fps']),
                '-c:a', 'aac', '-b:a', '160k', '-ar', '44100', '-ac', '2']
        if not self.audio:
            cmd += ['-shortest']
        if live and ts:
            cmd += ['-f', 'mpegts', 'pipe:1']
        elif live:
            cmd += ['-flvflags', 'no_duration_filesize', '-f', 'flv', o['url']]
        elif ts:
            cmd += ['-t', str(TEST_SECONDS), '-f', 'mpegts', str(self.preview_file.with_suffix('.ts'))]
        else:
            cmd += ['-t', str(TEST_SECONDS), '-movflags', '+faststart', str(self.preview_file)]
        return cmd

    def _mux_command(self):
        """Second FFmpeg for the phone encoder: takes the MPEG-TS and sends it unchanged to the RTMP server. Its progress is
        what really left the phone, so the live status reads it."""
        return ['ffmpeg', '-hide_banner', '-v', 'error', '-nostats', '-progress', 'pipe:1', '-f', 'mpegts', '-i', 'pipe:0',
                '-c', 'copy', '-flvflags', 'no_duration_filesize', '-f', 'flv', self.o['url']]

    def _read_progress(self, proc, start_at):
        info = {}
        for raw in proc.stdout:
            line = raw.decode('utf-8', 'replace').strip()
            if '=' not in line:
                continue
            k, v = line.split('=', 1)
            info[k] = v
            if k != 'progress':
                continue
            try:
                out = int(info.get('out_time_us') or 0) / 1e6
            except ValueError:
                out = 0
            position = start_at + max(0.0, out)
            if self.o['loop'] and self.duration:
                position %= self.duration
            frame = int(info.get('frame', '0') or 0)
            now = time.time()
            last_frame, last_time = self.fps_mark
            fps = (frame - last_frame) / (now - last_time) if now > last_time and frame >= last_frame else 0
            self.fps_mark = (frame, now)                # FFmpeg's own fps is an average that includes the start-up seconds
            fields = {'fps': round(fps, 1), 'bitrate': info.get('bitrate', '').strip(),
                      'speed': info.get('speed', '').strip(), 'dropped': int(info.get('drop_frames', '0') or 0),
                      'position': round(position, 1), 'frames': frame}
            if frame > 0 and self.state['status'] in ('connecting', 'reconnecting'):
                on_youtube = not self.broadcast or self.state.get('youtube') == 'live'
                fields.update(status='live', stage='🔴 Live on YouTube. Viewers can watch now.' if self.broadcast and on_youtube else
                              ('🔴 You are live' if on_youtube else 'Video is reaching YouTube ✓ · YouTube is starting the live (10–30 s)…'))
                self.ever_live = True
                self.started = self.started or time.time()
            self.state.update(fields)
            self.progress_out = out

    def _find_facecam(self):
        """Same as Make clips: look for the webcam box in the video. Without one, a face layout would show a random corner,
        so the video is cropped to fill the screen instead and the status says why."""
        self._set(stage='Finding the facecam in the video…')
        try:
            import facecam_detect
            found = facecam_detect.detect(self.src)
        except Exception as error:                                      # noqa: BLE001
            found = {'found': False, 'reason': str(error)[:120]}
        if found.get('found'):
            self.o['cam'], self.o['game'] = found['cam'], found['game']
            c = found['cam']
            self._set(facecam=f"Facecam found at {round(c['x'] * 100)}%, {round(c['y'] * 100)}% of the frame ({found.get('method')}, "
                              f"confidence {found.get('confidence')})")
        else:
            self.o['layout'] = 'fill' if self.o['format'] == 'shorts' else 'blur'
            self._set(facecam='No facecam in this video, so it fills the screen without one' +
                              (' (cropped)' if self.o['format'] == 'shorts' else ''))

    def _watch_youtube(self):
        """Show what YouTube says about the broadcast. With auto-start it turns live 10–30 s after video arrives."""
        while self.running() and not self.stop_flag.is_set():
            status = self.youtube.live_status(self.broadcast, self.o.get('channel'))
            if status:
                self.state['youtube'] = status
                if self.state['status'] == 'live':
                    self.state['stage'] = ('🔴 Live on YouTube. Viewers can watch now.' if status == 'live' else
                                           'Video is reaching YouTube ✓ · YouTube is starting the live (10–30 s)…')
            for _ in range(8):
                if self.stop_flag.is_set():
                    return
                time.sleep(1)

    def _read_errors(self, proc):
        for raw in proc.stderr:
            line = self._redact(raw.decode('utf-8', 'replace').strip())
            if line and 'Late SEI' not in line and 'upload a sample' not in line:
                self.errors.append(line)

    def _feed_layer(self, proc):
        try:
            while proc.poll() is None:
                proc.stdin.write(self.layer)
                proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass

    def _attempt(self, start_at, encoder):
        cmd = self._command(start_at, encoder)
        self.progress_out = 0
        self.state['frames'] = 0
        self.fps_mark = (0, time.time())
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.proc = proc
        mux = None
        if not self.o['test'] and encoders.via_ts(encoder):
            mux = subprocess.Popen(self._mux_command(), stdin=proc.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            proc.stdout.close()                        # the encoder now writes straight into the second FFmpeg
        self.mux = mux
        watched = mux or proc
        threads = [threading.Thread(target=self._read_progress, args=(watched, start_at), daemon=True),
                   threading.Thread(target=self._read_errors, args=(proc,), daemon=True)]
        if mux:
            threads.append(threading.Thread(target=self._read_errors, args=(mux,), daemon=True))
        if not self.o['test']:
            threads.append(threading.Thread(target=self._feed_layer, args=(proc,), daemon=True))
        else:
            proc.stdin.close()
        for t in threads:
            t.start()
        watched.wait()
        if mux:
            if proc.poll() is None:                    # the upload side stopped (network): stop the encoder too
                proc.terminate()
                try:
                    proc.wait(3)
                except subprocess.TimeoutExpired:
                    proc.kill()
            proc.wait()
        for t in threads[:2]:
            t.join(3)
        if mux:
            return mux.returncode if mux.returncode != 0 else proc.returncode
        return proc.returncode

    def _run(self):
        o = self.o
        try:
            self.src = self._source()
            if self.stop_flag.is_set():
                self._set(status='stopped', stage='Stopped before going live')
                return
            meta = self.probe(self.src)
            self.duration = meta['duration']
            self.audio = self._has_audio(self.src)
            self.state['duration'] = round(self.duration, 1)
            w, h = meta['w'], meta['h']
            if o['cam_auto'] and o['layout'] in FACE_LAYOUTS and not o['custom_cam']:
                self._find_facecam()
            self.rects = []
            for key in ('cam', 'game'):
                r = o[key]
                x = max(0, min(w - 2, int(r['x'] * w)))
                y = max(0, min(h - 2, int(r['y'] * h)))
                self.rects.append((x, y, max(2, min(w - x, int(r['w'] * w))), max(2, min(h - y, int(r['h'] * h)))))
            if o['layout'] == 'fill':
                # Crop to fill: cut the output's shape out of the source at the chosen spot (0 = left/top, 1 = right/bottom).
                self.rects[1] = crop_window(w, h, o['width'], o['height'], o['crop'])
                o['layout'] = 'game'
                self.state['layout'] = f"crop {round(o['crop'] * 100)}%"
            self.cam_file = styling.asset_path(self.data, o['custom_cam'], 'video') if o['custom_cam'] else None
            self.preview_file = self.data / (self.id + '.mp4')
            self.layer_file = self.data / (self.id + '.layer.png')
            self._render()
            if o['platform'] == 'youtube_auto' and not o['test']:
                self._set(status='connecting', stage='Creating the live on your YouTube channel…')
                if not self.youtube:
                    raise RuntimeError('YouTube is not set up in this app. Press ▶ Connect YouTube at the top first.')
                live = self.youtube.create_live(o['title'], o['description'], o['privacy'], channel=o.get('channel'))
                o['channel'] = live.get('channel') or o.get('channel')          # status checks and the end go to the same channel
                self.broadcast = live['broadcast_id']
                o['url'], o['key'] = live['server'] + '/' + live['key'], live['key']
                self._set(watch_url=live['watch_url'], studio_url=live['studio_url'], youtube='created',
                          destination=live.get('channel_title') or PLATFORMS['youtube_auto'][0])
                if self.stop_flag.is_set():
                    self._set(status='stopped', stage='Stopped before going live')
                    return
                threading.Thread(target=self._watch_youtube, daemon=True).start()
            hardware = True
            encoder = video_encoder(o['bitrate'], o['fps'])
            self._set(encoder=encoder[1])
            start_at, tries = 0.0, 0
            while not self.stop_flag.is_set():
                self._set(status='testing' if o['test'] else ('connecting' if not tries else 'reconnecting'),
                          stage=f'Test run: rendering {TEST_SECONDS} s…' if o['test'] else
                          (f'Connecting to {PLATFORMS[o["platform"]][0]}…' if not tries else f'Connection lost. Reconnecting ({tries}/{RETRIES})…'))
                code = self._attempt(start_at, encoder)
                got_frames = self.state.get('frames', 0) > 0
                if self.stop_flag.is_set():
                    self._set(status='stopped', stage='Live ended. You stopped it.' if not o['test'] else 'Test stopped.')
                    return
                if code == 0:
                    if o['test']:
                        if encoders.via_ts(encoder):                       # phone encoder wrote MPEG-TS: make the MP4 preview
                            encoders.finish_ts(self.preview_file.with_suffix('.ts'), self.preview_file)
                        for old in self.data.glob('golive*.mp4'):          # older test previews only, never a downloaded source (…dl.mp4)
                            if old != self.preview_file and PREVIEW.match(old.name):
                                old.unlink(missing_ok=True)
                        self._set(status='done', stage='Test ready. Play it below to check the layout, logo and banner.',
                                  preview='/media/' + self.id)
                    else:
                        self._set(status='done', stage='The video finished, so the live ended.')
                    return
                error = self._redact(' | '.join(list(self.errors)[-3:]))
                if hardware and not got_frames and encoder[1] != 'libx264':
                    hardware, encoder = False, video_encoder(o['bitrate'], o['fps'], hardware=False)   # the GPU encoder refused: use the CPU
                    self._set(encoder=encoder[1])
                    self.errors.clear()
                    continue
                if o['test'] or not self.ever_live or tries >= RETRIES:      # never on air = wrong key / server: say so at once
                    raise RuntimeError(friendly(error, o['platform']))
                tries += 1
                self._set(reconnects=tries)
                start_at = self.state.get('position', 0)                 # resume where the stream was
                time.sleep(min(10, 2 * tries))
        except Exception as error:                                      # noqa: BLE001
            message = self._redact(str(error))
            if 'TooLong' in type(error).__name__:
                message += ' Import the part you want in step 01 (it asks for the part), then choose "Use the video loaded above".'
            self._set(status='error', stage='Stopped with an error', error=message[-600:])
            try:
                import report
                report.log_error('go live', message[-600:])
            except Exception:                                           # noqa: BLE001
                pass
        finally:
            self.ended = time.time()
            if self.broadcast:
                self.youtube.end_live(self.broadcast, o.get('channel'))    # end it on YouTube too (or delete it if it never went on air)
                self.state['youtube'] = 'complete'
            if hasattr(self, 'preview_file') and o['test'] and self.state['status'] != 'done':
                self.preview_file.unlink(missing_ok=True)
            if hasattr(self, 'layer_file'):
                self.layer_file.unlink(missing_ok=True)


def attach(app, data, state, probe):
    sessions = {}

    def active():
        return next((s for s in sessions.values() if s.running()), None)

    def get(lid):
        if lid not in sessions:
            raise HTTPException(404, 'This live is not running any more (the app was restarted).')
        return sessions[lid]

    @app.post('/golive/start')
    def golive_start(b: dict):
        busy = active()
        if busy:
            raise HTTPException(409, 'A live (or test) is already running. Stop it first.')
        try:
            opts = settings(b, data)
        except ValueError as error:
            raise HTTPException(400, str(error))
        youtube = getattr(app.state, 'yt_manager', None)
        if opts['platform'] == 'youtube_auto' and not opts['test']:
            if not youtube or not youtube.get_credentials(opts['channel']):
                raise HTTPException(400, 'Connect your YouTube channel first: press ▶ Connect YouTube at the top.')
            if not youtube.live_allowed(opts['channel']):
                import youtube_uploader
                raise HTTPException(400, youtube_uploader.LIVE_PERMISSION)
        url, source = app.neon['new_source'](b)
        live = Live(data, probe, opts, url, source, state, app.neon['download'], youtube)
        # Remember the choices (never the stream key), so the phone app starts from the same logo, banner and format.
        last = {k: opts[k] for k in ('format', 'quality', 'fps', 'layout', 'crop', 'loop', 'platform', 'privacy', 'title')}
        last['overlay'] = dict(opts['overlay'])
        try:
            (data / 'golive_last.json').write_text(json.dumps(last), encoding='utf-8')
        except OSError:
            pass
        sessions[live.id] = live
        live.start()
        return {'live': live.id, 'state': live.status()}

    @app.get('/golive-last')
    def golive_last():
        try:
            return json.loads((data / 'golive_last.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    @app.get('/golive-active')
    def golive_active():
        live = active()
        return {'live': live.id if live else None}

    @app.get('/golive/{lid}')
    def golive_status(lid: str):
        return get(lid).status()

    @app.post('/golive/{lid}/overlay')
    def golive_overlay(lid: str, b: dict):
        try:
            return get(lid).update_overlay(b)
        except ValueError as error:
            raise HTTPException(400, str(error))

    @app.post('/golive/{lid}/stop')
    def golive_stop(lid: str):
        get(lid).stop()
        return {'ok': True}
