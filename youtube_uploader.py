"""YouTube integration for Ninja Studio Clipping.
Handles Google OAuth 2.0, several connected channels (add / switch / remove), and direct video uploads as YouTube Shorts.

Channels: every connected channel keeps its own login in data/youtube/channels/<channel id>.json, and
data/youtube/channels.json lists them and says which one is active. Uploads, batch uploads, auto-upload and Go Live use the
active channel unless a channel is given. An older single login (data/youtube/token.json) keeps working and is moved into the
list the first time its channel is known.
"""
from pathlib import Path
import os
import json
import hashlib
import uuid
import threading
import time
import logging
from typing import Optional, Dict, Any

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

logger = logging.getLogger("neonclipping.youtube")

LIVE_SCOPE = 'https://www.googleapis.com/auth/youtube'      # needed to create and end live broadcasts
SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.readonly',
    LIVE_SCOPE,
]
LIVE_PERMISSION = ('Allow live streaming for your channel once: press "Allow live streaming" (or ▶ Connect YouTube) and connect '
                   'the same channel again. Uploads keep working meanwhile.')
NOT_CONNECTED = 'YouTube channel is not connected. Connect account in Settings first.'


def live_error(error) -> str:
    """A readable message for the usual YouTube Live API refusals."""
    text = str(getattr(error, 'content', b'') or error)
    if isinstance(text, bytes):
        text = text.decode('utf-8', 'replace')
    if 'liveStreamingNotEnabled' in text:
        return ('Live streaming is not turned on for this channel yet. Open YouTube Studio → Create → Go live once and follow the steps '
                '(the first time YouTube can take up to 24 hours), then try again.')
    if 'insufficientPermissions' in text or 'ACCESS_TOKEN_SCOPE_INSUFFICIENT' in text:
        return LIVE_PERMISSION
    if 'quotaExceeded' in text or 'rateLimitExceeded' in text or 'userRequestsExceedRateLimit' in text:
        return 'YouTube says the daily API limit is used up for this app. Try again tomorrow, or use a stream key instead.'
    return 'YouTube refused to create the live: ' + text[-300:]


def _safe_id(channel_id: str) -> bool:
    return isinstance(channel_id, str) and 0 < len(channel_id) <= 64 and all(c.isalnum() or c in '-_' for c in channel_id)


class YouTubeManager:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.yt_dir = data_dir / 'youtube'
        self.yt_dir.mkdir(parents=True, exist_ok=True)
        self.secrets_file = self.yt_dir / 'client_secrets.json'
        self.legacy_token = self.yt_dir / 'token.json'          # the single login of older versions
        self.channels_dir = self.yt_dir / 'channels'
        self.index_file = self.yt_dir / 'channels.json'
        self.clients_dir = self.yt_dir / 'clients'              # other Google apps (client JSONs) used to add some channels
        self.config_file = self.yt_dir / 'config.json'
        self.uploads_file = self.yt_dir / 'uploads.json'
        self.pending_file = self.yt_dir / 'oauth_pending.json'
        self.upload_tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ channels
    def _index(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.index_file.read_text(encoding='utf-8'))
            if isinstance(data, dict) and isinstance(data.get('channels'), dict):
                return data
        except (OSError, ValueError):
            pass
        return {'active': None, 'channels': {}}

    def _save_index(self, data: Dict[str, Any]):
        tmp = self.index_file.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
        tmp.replace(self.index_file)

    def _channel_token(self, channel_id: str) -> Path:
        return self.channels_dir / f'{channel_id}.json'

    def active_channel(self) -> Optional[str]:
        """Id of the active channel, or None (then an older single login in token.json is used, if there is one)."""
        idx = self._index()
        ids = [c for c in idx['channels'] if self._channel_token(c).exists()]
        if idx.get('active') in ids:
            return idx['active']
        return ids[0] if ids else None

    def _resolve(self, channel: Optional[str]) -> Optional[str]:
        if channel:
            if channel not in self._index()['channels'] or not self._channel_token(channel).exists():
                raise RuntimeError('That YouTube channel is not connected any more. Choose another channel.')
            return channel
        return self.active_channel()

    @property
    def token_file(self) -> Path:
        """Login file of the active channel (or the older single login)."""
        active = self.active_channel()
        return self._channel_token(active) if active else self.legacy_token

    def _token_path(self, channel: Optional[str] = None) -> Path:
        cid = self._resolve(channel)
        return self._channel_token(cid) if cid else self.legacy_token

    def _remember(self, info: Dict[str, Any], token_json: str, make_active: bool = True, client: Optional[str] = None):
        """Store a channel's login and details; the newest connected channel becomes active.
        client: the Google app it signed in with ('' = the main client_secrets.json, None = keep what was saved)."""
        with self._lock:
            cid = info['id']
            self.channels_dir.mkdir(parents=True, exist_ok=True)
            self._channel_token(cid).write_text(token_json, encoding='utf-8')
            idx = self._index()
            old = idx['channels'].get(cid, {})
            idx['channels'][cid] = {k: info.get(k) for k in ('title', 'custom_url', 'thumbnail', 'subscribers', 'videos')}
            idx['channels'][cid]['added'] = old.get('added') or int(time.time())
            idx['channels'][cid]['client'] = (old.get('client') or '') if client is None else client
            if make_active or not idx.get('active'):
                idx['active'] = cid
            self._save_index(idx)

    def list_channels(self) -> Dict[str, Any]:
        """Connected channels from the saved list (no network), with which one is active and which may go live."""
        idx = self._index()
        active = self.active_channel()
        out = []
        for cid, info in idx['channels'].items():
            if not self._channel_token(cid).exists():
                continue
            out.append({'id': cid, **info, 'active': cid == active, 'live_allowed': self.live_allowed(cid)})
        return {'active': active, 'channels': out}

    def set_active(self, channel_id: str):
        with self._lock:
            idx = self._index()
            if channel_id not in idx['channels'] or not self._channel_token(channel_id).exists():
                raise RuntimeError('That channel is not connected.')
            idx['active'] = channel_id
            self._save_index(idx)

    def remove_channel(self, channel_id: str):
        """Forget a channel on this computer (nothing changes on YouTube). Another channel becomes active."""
        with self._lock:
            idx = self._index()
            if channel_id not in idx['channels']:
                raise RuntimeError('That channel is not connected.')
            client = idx['channels'].pop(channel_id).get('client')
            self._channel_token(channel_id).unlink(missing_ok=True)
            if idx.get('active') == channel_id:
                idx['active'] = next(iter(idx['channels']), None)
            self._save_index(idx)
            if client and not any(c.get('client') == client for c in idx['channels'].values()):
                (self.clients_dir / f'{client}.json').unlink(missing_ok=True)      # no channel uses that Google app any more

    # ------------------------------------------------------------------ uploads list
    def uploaded(self) -> Dict[str, Any]:
        """Clips already on YouTube, kept across restarts: {clip file id: {video_id, url, at, channel, channel_title, uploads}}."""
        try:
            data = json.loads(self.uploads_file.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _mark_uploaded(self, clip: str, video_id: str, url: str, channel: Optional[str] = None, channel_title: str = ''):
        with self._lock:
            data = self.uploaded()
            entry = {'video_id': video_id, 'url': url, 'at': int(time.time()), 'channel': channel, 'channel_title': channel_title}
            uploads = [u for u in data.get(clip, {}).get('uploads', []) if u.get('channel') != channel] + [entry]
            data[clip] = {**entry, 'uploads': uploads}           # top level = latest upload (what older versions read)
            tmp = self.uploads_file.with_suffix('.json.tmp')
            tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
            tmp.replace(self.uploads_file)

    def clip_states(self) -> Dict[str, Any]:
        """Per clip: uploaded (with link and the channels it is on), queued / uploading (with progress) or error."""
        out = {}
        for clip, info in self.uploaded().items():
            names = [u.get('channel_title') for u in info.get('uploads', []) if u.get('channel_title')]
            out[clip] = {'status': 'uploaded', **{k: v for k, v in info.items() if k != 'uploads'}, 'channels': names}
        for task in list(self.upload_tasks.values()):
            clip = task.get('clip_file')
            if not clip:
                continue
            if task['status'] in ('queued', 'starting', 'uploading'):
                out[clip] = {'status': task['status'], 'progress': task.get('progress', 0), 'channel_title': task.get('channel_title', '')}
            elif task['status'] == 'error' and clip not in out:
                out[clip] = {'status': 'error', 'error': str(task.get('error') or '')[:200]}
        return out

    # ------------------------------------------------------------------ settings
    def get_config(self) -> Dict[str, Any]:
        if self.config_file.exists():
            try:
                return json.loads(self.config_file.read_text(encoding='utf-8'))
            except Exception:
                pass
        return {'auto_upload': False, 'default_privacy': 'public', 'default_tags': ['Shorts', 'NinjaStudio']}

    def save_config(self, cfg: Dict[str, Any]):
        curr = self.get_config()
        curr.update(cfg)
        self.config_file.write_text(json.dumps(curr, indent=2), encoding='utf-8')

    def has_secrets(self) -> bool:
        return self.secrets_file.exists() and self.secrets_file.stat().st_size > 10

    def save_secrets_data(self, data: dict):
        self.secrets_file.write_text(json.dumps(data, indent=2), encoding='utf-8')

    # ------------------------------------------------------------------ other Google apps (optional, one per channel)
    @staticmethod
    def normalize_secrets(data) -> dict:
        """A Google OAuth client JSON as downloaded ({installed: …} or {web: …}) or just {client_id, client_secret}."""
        if isinstance(data, dict) and 'installed' not in data and 'web' not in data and 'client_id' in data:
            data = {'installed': {'client_id': data['client_id'], 'client_secret': data.get('client_secret', ''),
                                  'auth_uri': 'https://accounts.google.com/o/oauth2/auth', 'token_uri': 'https://oauth2.googleapis.com/token',
                                  'redirect_uris': ['http://127.0.0.1:8770/youtube/oauth2callback', 'http://localhost:8770/youtube/oauth2callback']}}
        inner = (data.get('installed') or data.get('web')) if isinstance(data, dict) else None
        if not isinstance(inner, dict) or not str(inner.get('client_id') or '').endswith('.apps.googleusercontent.com') \
                or not inner.get('client_secret'):
            raise ValueError('This is not a Google OAuth client JSON. In Google Cloud Console → APIs & Services → Credentials, '
                             'create an "OAuth client ID" of type Desktop app and download its JSON.')
        return data

    def save_client(self, data) -> str:
        """Keep another Google app's client JSON, so a channel can sign in through it (that project's own test users and
        daily upload quota). Returns its key; the same JSON again gives the same key."""
        data = self.normalize_secrets(data)
        inner = data.get('installed') or data.get('web')
        key = hashlib.sha256(inner['client_id'].encode()).hexdigest()[:16]
        self.clients_dir.mkdir(parents=True, exist_ok=True)
        (self.clients_dir / f'{key}.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
        return key

    def _secrets_path(self, client: Optional[str] = None) -> Path:
        if not client:
            return self.secrets_file
        path = self.clients_dir / f'{client}.json'
        if not (isinstance(client, str) and len(client) == 16 and all(c in '0123456789abcdef' for c in client)) or not path.exists():
            raise ValueError('That Google app JSON is not saved any more. Choose the JSON file again.')
        return path

    # ------------------------------------------------------------------ logins
    def get_credentials(self, channel: Optional[str] = None):
        """Valid login for a channel (default: the active one), refreshed when expired."""
        try:
            path = self._token_path(channel)
        except RuntimeError:
            return None
        if not path.exists():
            return None
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        try:
            # Keep the permissions this login was actually given: asking for more on refresh would fail until the user reconnects.
            creds = Credentials.from_authorized_user_file(str(path))
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                path.write_text(creds.to_json(), encoding='utf-8')
            if creds and creds.valid:
                return creds
        except Exception as e:
            logger.error("Error loading YouTube credentials: %s", e)
        return None

    @staticmethod
    def _channel_of(creds) -> Optional[Dict[str, Any]]:
        from googleapiclient.discovery import build
        yt = build('youtube', 'v3', credentials=creds, cache_discovery=False)
        res = yt.channels().list(mine=True, part='snippet,statistics').execute()
        items = res.get('items', [])
        if not items:
            return None
        snippet = items[0].get('snippet', {})
        stats = items[0].get('statistics', {})
        return {
            'id': items[0].get('id'),
            'title': snippet.get('title'),
            'custom_url': snippet.get('customUrl'),
            'thumbnail': snippet.get('thumbnails', {}).get('default', {}).get('url'),
            'subscribers': stats.get('subscriberCount', '0'),
            'videos': stats.get('videoCount', '0')
        }

    def get_channel_info(self, channel: Optional[str] = None) -> Optional[Dict[str, Any]]:
        creds = self.get_credentials(channel)
        if not creds:
            return None
        try:
            info = self._channel_of(creds)
        except Exception as e:
            logger.error("Failed to fetch channel info: %s", e)
            return None
        if info and info.get('id') and _safe_id(info['id']):
            cid = self._resolve(channel)
            if cid is None and self.legacy_token.exists():
                # an older single login: move it into the channel list now that its channel is known
                self._remember(info, self.legacy_token.read_text(encoding='utf-8'), make_active=not self.active_channel())
                self.legacy_token.unlink(missing_ok=True)
            elif cid == info['id']:
                self._remember(info, self._channel_token(cid).read_text(encoding='utf-8'), make_active=False)
        return info

    def live_allowed(self, channel: Optional[str] = None) -> bool:
        """True when the saved login includes the permission to create live broadcasts (older logins only had upload)."""
        try:
            scopes = set(json.loads(self._token_path(channel).read_text(encoding='utf-8')).get('scopes') or [])
        except (OSError, ValueError, RuntimeError):
            return False
        return bool(scopes & {LIVE_SCOPE, 'https://www.googleapis.com/auth/youtube.force-ssl'})

    def _youtube(self, channel: Optional[str] = None):
        creds = self.get_credentials(channel)
        if not creds:
            raise RuntimeError('Your YouTube channel is not connected. Press ▶ Connect YouTube at the top first.')
        if not self.live_allowed(channel):
            raise RuntimeError(LIVE_PERMISSION)
        from googleapiclient.discovery import build
        return build('youtube', 'v3', credentials=creds, cache_discovery=False)

    def channel_title(self, channel: Optional[str] = None) -> str:
        cid = self._resolve(channel)
        return (self._index()['channels'].get(cid) or {}).get('title') or '' if cid else ''

    # ------------------------------------------------------------------ live
    def create_live(self, title: str, description: str = '', privacy: str = 'public', channel: Optional[str] = None) -> Dict[str, Any]:
        """Make a live broadcast on a connected channel (default: active) and the stream that feeds it, and bind them.
        The broadcast starts by itself when video arrives (enableAutoStart) and ends when it stops (enableAutoStop)."""
        from googleapiclient.errors import HttpError
        from datetime import datetime, timezone
        yt = self._youtube(channel)
        title = (title or 'Live').strip()[:100]
        try:
            stream = yt.liveStreams().insert(part='snippet,cdn,contentDetails', body={
                'snippet': {'title': title},
                'cdn': {'ingestionType': 'rtmp', 'resolution': 'variable', 'frameRate': 'variable'},
                'contentDetails': {'isReusable': False}}).execute()
            broadcast = yt.liveBroadcasts().insert(part='snippet,status,contentDetails', body={
                'snippet': {'title': title, 'description': (description or '')[:4900],
                            'scheduledStartTime': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')},
                'status': {'privacyStatus': privacy if privacy in ('public', 'unlisted', 'private') else 'public',
                           'selfDeclaredMadeForKids': False},
                'contentDetails': {'enableAutoStart': True, 'enableAutoStop': True, 'enableDvr': True,
                                   'recordFromStart': True, 'latencyPreference': 'low'}}).execute()
            yt.liveBroadcasts().bind(id=broadcast['id'], part='id,contentDetails', streamId=stream['id']).execute()
        except HttpError as e:
            raise RuntimeError(live_error(e))
        ingest = stream['cdn']['ingestionInfo']
        return {'broadcast_id': broadcast['id'], 'stream_id': stream['id'], 'server': ingest['ingestionAddress'].rstrip('/'),
                'key': ingest['streamName'], 'watch_url': 'https://www.youtube.com/watch?v=' + broadcast['id'],
                'studio_url': f"https://studio.youtube.com/video/{broadcast['id']}/livestreaming",
                'channel': self._resolve(channel), 'channel_title': self.channel_title(channel)}

    def live_status(self, broadcast_id: str, channel: Optional[str] = None) -> str:
        """YouTube's view of the broadcast: created / ready / testing / live / complete (or '' if unknown)."""
        try:
            items = self._youtube(channel).liveBroadcasts().list(part='status', id=broadcast_id).execute().get('items', [])
            return items[0]['status'].get('lifeCycleStatus', '') if items else ''
        except Exception as e:                                       # noqa: BLE001
            logger.warning('live status check failed: %s', e)
            return ''

    def end_live(self, broadcast_id: str, channel: Optional[str] = None):
        """End the broadcast on YouTube. One that never went on air is deleted, so no empty 'upcoming' live is left behind."""
        try:
            yt = self._youtube(channel)
            status = self.live_status(broadcast_id, channel)
            if status in ('live', 'liveStarting'):
                yt.liveBroadcasts().transition(broadcastStatus='complete', id=broadcast_id, part='status').execute()
            elif status in ('created', 'ready', 'testing', 'testStarting'):
                yt.liveBroadcasts().delete(id=broadcast_id).execute()
        except Exception as e:                                       # noqa: BLE001
            logger.warning('ending the YouTube live failed: %s', e)

    # ------------------------------------------------------------------ status / connect
    def get_status(self) -> Dict[str, Any]:
        has_sec = self.has_secrets()
        creds = self.get_credentials()
        channel = self.get_channel_info() if creds else None
        cfg = self.get_config()
        listed = self.list_channels()
        return {
            'has_secrets': has_sec,
            'connected': bool(creds and channel),
            'live_allowed': bool(creds) and self.live_allowed(),
            'channel': channel,
            'channels': listed['channels'],
            'active_channel': listed['active'],
            'auto_upload': cfg.get('auto_upload', False),
            'default_privacy': cfg.get('default_privacy', 'public')
        }

    def disconnect(self):
        """Disconnect the active channel (the other connected channels stay)."""
        active = self.active_channel()
        if active:
            self.remove_channel(active)
        elif self.legacy_token.exists():
            self.legacy_token.unlink()

    def get_auth_url(self, redirect_uri: str, client: Optional[str] = None) -> str:
        """Google sign-in link, through the main client_secrets.json or (client) another saved Google app."""
        if not client and not self.has_secrets():
            raise ValueError("client_secrets.json not found. Please provide OAuth credentials first.")
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self._secrets_path(client)),
            scopes=SCOPES
        )
        flow.redirect_uri = redirect_uri
        auth_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent select_account'        # always show the account / channel chooser, so another channel can be added
        )
        # Google's login uses PKCE: the secret "code verifier" made for this link must be sent again when the code comes back,
        # or Google answers "invalid_grant: Missing code verifier". Keep it until then (on disk, so a restart in between is fine).
        self._save_pending(state, flow.code_verifier, redirect_uri, client)
        return auth_url

    def _save_pending(self, state: str, verifier: Optional[str], redirect_uri: str, client: Optional[str] = None):
        with self._lock:
            pending = {k: v for k, v in self._pending().items() if time.time() - v.get('at', 0) < 3600}   # drop links older than 1 h
            pending[state] = {'verifier': verifier, 'redirect_uri': redirect_uri, 'client': client or '', 'at': time.time()}
            self.pending_file.write_text(json.dumps(pending), encoding='utf-8')

    def _pending(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.pending_file.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _take_pending(self, state: Optional[str]) -> Dict[str, Any]:
        """The login link this code belongs to (by its state), or the newest one when the code was pasted by hand."""
        with self._lock:
            pending = self._pending()
            key = state if state in pending else max(pending, key=lambda k: pending[k].get('at', 0), default=None)
            found = pending.pop(key, {}) if key else {}
            self.pending_file.write_text(json.dumps(pending), encoding='utf-8')
            return found

    def _store_login(self, creds, client: str = '') -> Optional[Dict[str, Any]]:
        """After a successful Google login: add (or refresh) that channel and make it the active one.
        The saved login carries its own app's client id and secret, so it keeps refreshing through that app."""
        info = None
        try:
            info = self._channel_of(creds)
        except Exception as e:                                       # noqa: BLE001
            logger.error("Failed to fetch channel info after login: %s", e)
        if info and info.get('id') and _safe_id(info['id']):
            self._remember(info, creds.to_json(), client=client or '')
            return info
        if info is None:
            # the login worked but the channel could not be read (offline?): keep it as the single login until it can be
            self.legacy_token.write_text(creds.to_json(), encoding='utf-8')
            return None
        raise RuntimeError('This Google account has no YouTube channel yet. Create one on youtube.com, or pick another account.')

    def start_local_auth(self, port=8080):
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.secrets_file),
            scopes=SCOPES
        )
        creds = flow.run_local_server(port=port, open_browser=True, prompt='consent select_account')
        return self._store_login(creds)

    def finish_auth_code(self, code: str, redirect_uri: str, state: Optional[str] = None):
        from google_auth_oauthlib.flow import Flow
        pending = self._take_pending(state)
        client = pending.get('client') or ''
        flow = Flow.from_client_secrets_file(
            str(self._secrets_path(client)),
            scopes=SCOPES,
            redirect_uri=pending.get('redirect_uri') or redirect_uri,
            state=state
        )
        if pending.get('verifier'):
            flow.code_verifier = pending['verifier']
        flow.fetch_token(code=code)
        return self._store_login(flow.credentials, client)

    # ------------------------------------------------------------------ uploads
    def _find_clip(self, clip_id: str) -> Path:
        # Locate clip file robustly
        clean_id = clip_id
        for prefix in ('ninjastudio-live-', 'ninjastudio-', 'neonclipping-live-', 'neonclipping-'):
            clean_id = clean_id.replace(prefix, '')
        if clean_id.endswith('.mp4'):
            clean_id = clean_id[:-4]
        candidates = [
            self.data_dir / f"{clean_id}.mp4",
            self.data_dir / f"{clip_id}.mp4",
            self.data_dir / clip_id,
            Path(clip_id)
        ]
        file_path = None
        for cand in candidates:
            if cand.exists() and cand.is_file():
                file_path = cand
                break
        if not file_path:
            raise FileNotFoundError(f"Clip file '{clip_id}' not found in {self.data_dir}")
        return file_path

    def _new_task(self, clip_id: str, file_path: Path, title: str, status: str = 'starting', channel: Optional[str] = None) -> str:
        task_id = uuid.uuid4().hex
        self.upload_tasks[task_id] = {
            'id': task_id,
            'clip_id': clip_id,
            'clip_file': file_path.stem,
            'status': status,
            'progress': 0,
            'title': title,
            'channel': channel,
            'channel_title': self.channel_title(channel) if channel else '',
            'video_id': None,
            'url': None,
            'error': None
        }
        return task_id

    def _upload_channel(self, channel: Optional[str]) -> Optional[str]:
        """The channel an upload goes to (default: active). Raises when it has no working login."""
        cid = self._resolve(channel)
        if not self.get_credentials(cid):
            raise RuntimeError(NOT_CONNECTED)
        return cid

    def start_upload(self, clip_id: str, title: str, description: str = '', privacy: str = 'public', tags=None,
                     channel: Optional[str] = None) -> str:
        """Starts asynchronous video upload to YouTube (to the given channel, default: active)."""
        cid = self._upload_channel(channel)
        file_path = self._find_clip(clip_id)
        task_id = self._new_task(clip_id, file_path, title, channel=cid)

        # Background worker
        t = threading.Thread(
            target=self._upload_worker,
            args=(task_id, file_path, title, description, privacy, tags or [], cid),
            daemon=True
        )
        t.start()
        return task_id

    def start_batch(self, items: list, privacy: str = 'public', tags=None, description: str = '', channel: Optional[str] = None) -> list:
        """Queue several clips and upload them one after another (one at a time is kinder to the YouTube quota)."""
        cid = self._upload_channel(channel)
        jobs = []
        for item in items:
            clip_id = str(item.get('clip_id') or '')
            title = str(item.get('title') or 'Short clip')[:100]
            try:
                if not clip_id.isalnum():
                    raise FileNotFoundError(f"Clip '{clip_id[:40]}' not found")
                file_path = self._find_clip(clip_id)
            except FileNotFoundError as e:
                jobs.append({'clip_id': clip_id, 'error': str(e)})
                continue
            task_id = self._new_task(clip_id, file_path, title, 'queued', channel=cid)
            jobs.append({'clip_id': clip_id, 'task_id': task_id,
                         '_args': (task_id, file_path, title, str(item.get('description') or description)[:4900], privacy, list(tags or []), cid)})

        def run():
            for job in jobs:
                if '_args' in job:
                    self._upload_worker(*job['_args'])
        threading.Thread(target=run, daemon=True).start()
        return [{k: v for k, v in job.items() if k != '_args'} for job in jobs]

    def _upload_worker(self, task_id: str, file_path: Path, title: str, description: str, privacy: str, tags: list,
                       channel: Optional[str] = None):
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        from googleapiclient.errors import HttpError

        try:
            self.upload_tasks[task_id]['status'] = 'uploading'
            self.upload_tasks[task_id]['stage'] = 'Connecting to YouTube...'
            creds = self.get_credentials(channel)
            if not creds:
                raise RuntimeError(NOT_CONNECTED)
            yt = build('youtube', 'v3', credentials=creds)

            # Ensure #Shorts tag
            if "#Shorts" not in title and "#shorts" not in title:
                upload_title = f"{title} #Shorts"[:100]
            else:
                upload_title = title[:100]

            upload_tags = list(tags) if tags else []
            if "Shorts" not in upload_tags and "shorts" not in upload_tags:
                upload_tags.append("Shorts")

            body = {
                'snippet': {
                    'title': upload_title,
                    'description': description or f"{upload_title}\n\nGenerated with Ninja Studio Clipping\n#Shorts #Viral",
                    'tags': upload_tags,
                    'categoryId': '22'  # People & Blogs / General
                },
                'status': {
                    'privacyStatus': privacy if privacy in ('public', 'unlisted', 'private') else 'public',
                    'selfDeclaredMadeForKids': False
                }
            }

            media = MediaFileUpload(
                str(file_path),
                mimetype='video/mp4',
                chunksize=1024 * 1024 * 2,  # 2MB chunks
                resumable=True
            )

            request = yt.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=media
            )

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    prog = float(status.progress())
                    self.upload_tasks[task_id]['progress'] = round(prog, 2)
                    self.upload_tasks[task_id]['stage'] = f"Uploading... {int(prog * 100)}%"

            video_id = response.get('id')
            video_url = f"https://youtube.com/shorts/{video_id}"
            self.upload_tasks[task_id]['status'] = 'done'
            self.upload_tasks[task_id]['progress'] = 1.0
            self.upload_tasks[task_id]['stage'] = 'Uploaded successfully'
            self.upload_tasks[task_id]['video_id'] = video_id
            self.upload_tasks[task_id]['url'] = video_url
            self._mark_uploaded(file_path.stem, video_id, video_url, channel, self.upload_tasks[task_id].get('channel_title', ''))

        except HttpError as e:
            err_msg = f"YouTube API Error {e.resp.status}: {e.content.decode('utf-8') if hasattr(e, 'content') else str(e)}"
            logger.error(err_msg)
            self.upload_tasks[task_id]['status'] = 'error'
            self.upload_tasks[task_id]['error'] = err_msg
        except Exception as e:
            logger.error("Upload error: %s", e)
            self.upload_tasks[task_id]['status'] = 'error'
            self.upload_tasks[task_id]['error'] = str(e)


def attach(app: FastAPI, data_dir: Path, state: dict):
    yt = YouTubeManager(data_dir)
    app.state.yt_manager = yt

    @app.get('/youtube/status')
    def get_status():
        return yt.get_status()

    @app.get('/youtube/channels')
    def channels():
        return yt.list_channels()

    @app.post('/youtube/channels/active')
    def channel_active(body: dict):
        try:
            yt.set_active(str(body.get('id') or ''))
        except RuntimeError as e:
            raise HTTPException(400, str(e))
        return yt.list_channels()

    @app.post('/youtube/channels/remove')
    def channel_remove(body: dict):
        try:
            yt.remove_channel(str(body.get('id') or ''))
        except RuntimeError as e:
            raise HTTPException(400, str(e))
        return yt.list_channels()

    @app.post('/youtube/config')
    def set_config(cfg: dict):
        yt.save_config(cfg)
        return {'ok': True, 'config': yt.get_config()}

    @app.post('/youtube/secrets')
    async def upload_secrets(request: Request):
        try:
            content_type = request.headers.get('content-type', '')
            if 'multipart/form-data' in content_type:
                form = await request.form()
                file = form.get('file')
                if not file:
                    raise HTTPException(400, 'No file uploaded')
                data_bytes = await file.read()
                data = json.loads(data_bytes.decode('utf-8'))
            else:
                data = await request.json()

            # Normalize credentials json if needed
            if 'installed' not in data and 'web' not in data and 'client_id' in data:
                data = {
                    "installed": {
                        "client_id": data["client_id"],
                        "client_secret": data.get("client_secret", ""),
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://127.0.0.1:8770/youtube/oauth2callback", "http://localhost:8770/youtube/oauth2callback"]
                    }
                }

            yt.save_secrets_data(data)
            return {'ok': True, 'message': 'client_secrets.json saved successfully!'}
        except json.JSONDecodeError:
            raise HTTPException(400, 'Invalid JSON format.')
        except Exception as e:
            raise HTTPException(400, str(e))

    @app.get('/youtube/auth-url')
    def get_auth_url(request: Request):
        redirect_uri = f"{request.base_url._url.rstrip('/')}/youtube/oauth2callback"
        try:
            url = yt.get_auth_url(redirect_uri)
            return {'url': url, 'redirect_uri': redirect_uri}
        except Exception as e:
            raise HTTPException(400, str(e))

    @app.post('/youtube/auth-url-client')
    def get_auth_url_client(body: dict, request: Request):
        """Add a channel through another Google app: save its client JSON, then sign in with it."""
        redirect_uri = f"{request.base_url._url.rstrip('/')}/youtube/oauth2callback"
        try:
            client = yt.save_client(body.get('secrets'))
            return {'url': yt.get_auth_url(redirect_uri, client=client), 'redirect_uri': redirect_uri, 'client': client}
        except Exception as e:
            raise HTTPException(400, str(e))

    @app.post('/youtube/auth-start')
    def start_auth_local():
        def run():
            try:
                yt.start_local_auth(port=8080)
            except Exception as e:
                logger.error("Local auth error: %s", e)
        t = threading.Thread(target=run, daemon=True)
        t.start()
        return {'ok': True, 'message': 'Authentication started. Browser will open.'}

    @app.get('/youtube/oauth2callback')
    def oauth_callback(code: Optional[str] = None, error: Optional[str] = None, state: Optional[str] = None, request: Request = None):
        if error:
            return HTMLResponse(f"<h3>Authentication Failed</h3><p>{error}</p><a href='/'>Back to Ninja Studio Clipping</a>")
        if not code:
            return HTMLResponse("<h3>Missing Code</h3><a href='/'>Back to Ninja Studio Clipping</a>")

        redirect_uri = f"{request.base_url._url.rstrip('/')}/youtube/oauth2callback"
        try:
            channel = yt.finish_auth_code(code, redirect_uri, state)
            return HTMLResponse(f"""
            <html>
            <head><meta http-equiv="refresh" content="2;url=/?youtube=connected"></head>
            <body style="font-family:sans-serif;text-align:center;padding:50px;background:#0f1015;color:#fff;">
                <h2 style="color:#22c55e;">Connected to YouTube!</h2>
                <p>Channel: <b>{channel.get('title') if channel else 'Connected'}</b></p>
                <p>Redirecting back to Ninja Studio Clipping...</p>
                <script>
                    if (window.opener) {{
                        window.opener.postMessage('youtube_connected', '*');
                        window.close();
                    }}
                </script>
            </body>
            </html>
            """)
        except Exception as e:
            return HTMLResponse(f"<h3>OAuth Verification Error</h3><p>{e}</p><a href='/'>Back to Ninja Studio Clipping</a>")

    @app.post('/youtube/auth-code')
    def manual_code(body: dict, request: Request):
        code = body.get('code')
        if not code:
            raise HTTPException(400, 'Code is required.')
        redirect_uri = body.get('redirect_uri') or f"{request.base_url._url.rstrip('/')}/youtube/oauth2callback"
        try:
            channel = yt.finish_auth_code(code.strip(), redirect_uri, body.get('state'))
            return {'ok': True, 'channel': channel}
        except Exception as e:
            raise HTTPException(400, str(e))

    @app.post('/youtube/disconnect')
    def disconnect():
        yt.disconnect()
        return {'ok': True, 'message': 'Disconnected from YouTube.'}

    @app.post('/youtube/upload')
    def upload_clip(body: dict):
        clip_id = body.get('clip_id')
        if not clip_id:
            raise HTTPException(400, 'clip_id is required.')
        title = body.get('title') or 'Short clip'
        description = body.get('description', '')
        privacy = body.get('privacy', 'public')
        tags = body.get('tags', [])

        try:
            task_id = yt.start_upload(
                clip_id=clip_id,
                title=title,
                description=description,
                privacy=privacy,
                tags=tags,
                channel=body.get('channel') or None
            )
            return {'ok': True, 'task_id': task_id}
        except Exception as e:
            raise HTTPException(400, str(e))

    @app.post('/youtube/upload-batch')
    def upload_batch(body: dict):
        items = body.get('items')
        if not isinstance(items, list) or not 1 <= len(items) <= 100 or not all(isinstance(i, dict) for i in items):
            raise HTTPException(400, 'Choose 1 to 100 clips to upload.')
        cfg = yt.get_config()
        try:
            jobs = yt.start_batch(items, body.get('privacy') or cfg.get('default_privacy', 'public'),
                                  body.get('tags') or cfg.get('default_tags', ['Shorts']), str(body.get('description') or ''),
                                  channel=body.get('channel') or None)
        except RuntimeError as e:
            raise HTTPException(400, str(e))
        return {'ok': True, 'jobs': jobs}

    @app.get('/youtube/clip-states')
    def clip_states():
        return yt.clip_states()

    @app.get('/youtube/upload-status/{task_id}')
    def upload_status(task_id: str):
        task = yt.upload_tasks.get(task_id)
        if not task:
            raise HTTPException(404, 'Upload task not found.')
        return task
