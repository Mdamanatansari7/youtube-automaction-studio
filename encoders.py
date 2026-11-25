"""Pick the H.264 video encoder that really works on this computer (NVIDIA, Apple, or plain CPU), instead of always trying NVENC first.

Order: NVENC (NVIDIA GPU) -> AMF (AMD GPU) -> QSV (Intel GPU) -> VideoToolbox (Mac) -> libx264 (any CPU). On an Android phone (Termux)
it is MediaCodec (the phone's hardware encoder) -> libx264. Each hardware encoder is used only if ffmpeg lists it AND a tiny test
encode succeeds, so a Mac or a PC without an NVIDIA card goes straight to the right one with no failed first attempt.
Override with NEONCLIPPING_ENCODER = nvenc | amf | qsv | videotoolbox | mediacodec | x264 | auto (default).
The functions return lists of ffmpeg argument lists, best first; callers keep the old pattern "try each until one works".
"""
from functools import lru_cache
import os, subprocess


@lru_cache(maxsize=1)
def _listed():
    try:
        out = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    return frozenset(name for name in ('h264_nvenc', 'h264_amf', 'h264_qsv', 'h264_videotoolbox', 'h264_mediacodec') if name in out)


def android():
    """True inside Termux on an Android phone (the phone app's engine)."""
    return 'com.termux' in os.environ.get('PREFIX', '') or os.path.exists('/system/build.prop')


MEDIACODEC = ['-c:v', 'h264_mediacodec', '-ndk_codec', '1', '-pix_fmt', 'nv12']    # the phone's hardware encoder, without Java


@lru_cache(maxsize=6)
def works(name):
    """True if ffmpeg lists this encoder and can encode a tiny test clip with it."""
    if name == 'libx264':
        return True
    if name not in _listed():
        return False
    if name == 'h264_mediacodec':
        # Some phones (and every emulator) open the encoder but return no frames, so check that real frames come out.
        try:
            r = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=640x360:r=30:d=1', *MEDIACODEC,
                                '-b:v', '2M', '-f', 'h264', '-'], capture_output=True, timeout=25)
            return r.returncode == 0 and len(r.stdout) > 2000
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        r = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=256x256:d=0.2', '-frames:v', '3',
                            '-c:v', name, '-f', 'null', '-'], capture_output=True, timeout=25)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def h264(cq=20, x264_preset='fast', nv_preset='p5', vt_bitrate='14M'):
    """Encoder argument lists to try in order. The last one (libx264) always exists."""
    pick = os.environ.get('NEONCLIPPING_ENCODER', 'auto').strip().lower()
    options = {
        'nvenc': ['-c:v', 'h264_nvenc', '-preset', nv_preset, '-cq', str(cq)],
        'amf': ['-c:v', 'h264_amf', '-quality', 'quality', '-rc', 'cqp', '-qp_i', str(cq), '-qp_p', str(cq)],
        'qsv': ['-c:v', 'h264_qsv', '-global_quality', str(cq), '-preset', 'medium'],
        'videotoolbox': ['-c:v', 'h264_videotoolbox', '-b:v', vt_bitrate, '-allow_sw', '1'],
        'mediacodec': [*MEDIACODEC, '-b:v', vt_bitrate],
        'x264': ['-c:v', 'libx264', '-crf', str(cq), '-preset', 'veryfast' if android() else x264_preset],
    }
    names = {'nvenc': 'h264_nvenc', 'amf': 'h264_amf', 'qsv': 'h264_qsv', 'videotoolbox': 'h264_videotoolbox',
             'mediacodec': 'h264_mediacodec', 'x264': 'libx264'}
    order = [pick] if pick in options else (['mediacodec'] if android() else ['nvenc', 'amf', 'qsv', 'videotoolbox'])
    out = [options[k] for k in order if k != 'x264' and works(names[k])]
    out.append(options['x264'])
    return out


def via_ts(encoder):
    """The phone's MediaCodec encoder only delivers video when writing MPEG-TS (MP4 and FLV come out empty), so with it
    an encode goes to .ts first and is then repackaged without re-encoding (finish_ts)."""
    return 'h264_mediacodec' in encoder


def finish_ts(ts, out):
    """Repackage an MPEG-TS encode into the wanted .mp4 (no quality loss) and remove the .ts."""
    r = subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(ts), '-c', 'copy', '-movflags', '+faststart', str(out)],
                       capture_output=True, text=True)
    try:
        os.remove(ts)
    except OSError:
        pass
    return r


def describe():
    """For the diagnostics text: which encoder will be used first."""
    return h264()[0][1]
