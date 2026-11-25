"""Several YouTube channels: add, switch, remove, the older single login, and uploads to a chosen channel (Google faked)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import youtube_uploader  # noqa: E402

LOGIN = {'token': 't', 'refresh_token': 'r', 'client_id': 'c', 'client_secret': 's',
         'token_uri': 'https://oauth2.googleapis.com/token', 'scopes': [youtube_uploader.LIVE_SCOPE],
         'expiry': '2099-01-01T00:00:00Z'}                              # still valid: no refresh, no network


class FakeCreds:
    def __init__(self, cid):
        self.cid = cid

    def to_json(self):
        return json.dumps({**LOGIN, 'token': 't-' + self.cid})


def channel(cid):
    return {'id': cid, 'title': 'Channel ' + cid, 'custom_url': '@' + cid.lower(), 'thumbnail': None, 'subscribers': '5', 'videos': '1'}


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.mgr = youtube_uploader.YouTubeManager(self.data)
        # Google answers "this login belongs to channel <cid>"
        self.patch = mock.patch.object(youtube_uploader.YouTubeManager, '_channel_of',
                                       side_effect=lambda creds: channel(getattr(creds, 'cid', None) or 'UCold'))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def login(self, cid):
        return self.mgr._store_login(FakeCreds(cid))

    def ids(self):
        return [c['id'] for c in self.mgr.list_channels()['channels']]

    def test_add_two_channels_and_switch(self):
        self.login('UCa')
        self.login('UCb')
        self.assertEqual(self.ids(), ['UCa', 'UCb'])
        self.assertEqual(self.mgr.active_channel(), 'UCb')              # the newest connected channel is active
        self.mgr.set_active('UCa')
        listed = self.mgr.list_channels()
        self.assertEqual(listed['active'], 'UCa')
        self.assertEqual([c['active'] for c in listed['channels']], [True, False])
        self.assertTrue(all(c['live_allowed'] for c in listed['channels']))
        self.assertEqual(self.mgr.get_credentials().token, 't-UCa')
        self.assertEqual(self.mgr.get_credentials('UCb').token, 't-UCb')
        self.login('UCb')                                                # connecting it again: still one entry
        self.assertEqual(self.ids(), ['UCa', 'UCb'])
        with self.assertRaises(RuntimeError):
            self.mgr.set_active('UCnope')

    def test_remove_and_disconnect(self):
        self.login('UCa')
        self.login('UCb')
        self.mgr.remove_channel('UCb')
        self.assertEqual((self.ids(), self.mgr.active_channel()), (['UCa'], 'UCa'))
        self.assertFalse((self.data / 'youtube' / 'channels' / 'UCb.json').exists())
        self.mgr.disconnect()
        self.assertEqual((self.ids(), self.mgr.active_channel(), self.mgr.get_credentials()), ([], None, None))

    def test_older_single_login_is_moved_into_the_list(self):
        (self.data / 'youtube' / 'token.json').write_text(json.dumps(LOGIN), encoding='utf-8')
        self.assertEqual(self.mgr.get_credentials().token, 't')         # works before it is moved
        self.assertEqual(self.mgr.get_channel_info()['id'], 'UCold')
        self.assertEqual((self.ids(), self.mgr.active_channel()), (['UCold'], 'UCold'))
        self.assertFalse((self.data / 'youtube' / 'token.json').exists())
        status = self.mgr.get_status()
        self.assertTrue(status['connected'])
        self.assertEqual((status['active_channel'], [c['title'] for c in status['channels']]), ('UCold', ['Channel UCold']))

    def test_account_without_a_channel_is_refused(self):
        with mock.patch.object(youtube_uploader.YouTubeManager, '_channel_of', return_value={}):
            with self.assertRaises(RuntimeError):
                self.login('UCa')
        self.assertEqual(self.ids(), [])

    def test_upload_goes_to_the_chosen_channel(self):
        self.login('UCa')
        self.login('UCb')                                                # active = UCb
        (self.data / 'abc123.mp4').write_bytes(b'x')
        with mock.patch.object(youtube_uploader.YouTubeManager, '_upload_worker') as worker:
            task = self.mgr.start_upload('abc123', 'Hello', channel='UCa')
            self.mgr.start_upload('abc123', 'Hello')
            jobs = self.mgr.start_batch([{'clip_id': 'abc123', 'title': 'One'}], channel='UCa')
        self.assertEqual(self.mgr.upload_tasks[task]['channel_title'], 'Channel UCa')
        used = [c.args[-1] for c in worker.call_args_list]
        self.assertEqual(sorted(used[:2]), ['UCa', 'UCb'])
        self.assertEqual(self.mgr.upload_tasks[jobs[0]['task_id']]['channel'], 'UCa')
        with self.assertRaises(RuntimeError):
            self.mgr.start_upload('abc123', 'Hello', channel='UCgone')

    def test_clip_on_two_channels(self):
        self.mgr._mark_uploaded('abc123', 'v1', 'https://youtube.com/shorts/v1', 'UCa', 'Channel UCa')
        self.mgr._mark_uploaded('abc123', 'v2', 'https://youtube.com/shorts/v2', 'UCb', 'Channel UCb')
        self.mgr._mark_uploaded('abc123', 'v3', 'https://youtube.com/shorts/v3', 'UCa', 'Channel UCa')   # again: replaces
        state = self.mgr.clip_states()['abc123']
        self.assertEqual((state['status'], state['video_id']), ('uploaded', 'v3'))
        self.assertEqual(state['channels'], ['Channel UCb', 'Channel UCa'])

    def test_add_channel_through_its_own_google_app(self):
        from urllib.parse import parse_qs, urlparse
        from google_auth_oauthlib.flow import Flow
        from requests_oauthlib import OAuth2Session
        with self.assertRaises(ValueError):
            self.mgr.save_client({'hello': 'world'})
        key = self.mgr.save_client({'installed': {'client_id': 'other.apps.googleusercontent.com', 'client_secret': 'sec2',
                                                  'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                                                  'token_uri': 'https://oauth2.googleapis.com/token'}})
        self.assertEqual(key, self.mgr.save_client({'client_id': 'other.apps.googleusercontent.com', 'client_secret': 'sec2'}))
        redirect = 'http://127.0.0.1:8770/youtube/oauth2callback'
        q = parse_qs(urlparse(self.mgr.get_auth_url(redirect, client=key)).query)    # works without a main client_secrets.json
        self.assertEqual(q['client_id'][0], 'other.apps.googleusercontent.com')
        sent = {}

        def fake_google(session, token_url, **kw):
            sent.update(kw, client_id=session.client_id)
            return {'access_token': 't', 'token_type': 'Bearer'}
        with mock.patch.object(OAuth2Session, 'fetch_token', autospec=True, side_effect=fake_google), \
                mock.patch.object(Flow, 'credentials', new_callable=mock.PropertyMock, return_value=FakeCreds('UCz')):
            self.mgr.finish_auth_code('code', redirect, q['state'][0])
        self.assertEqual(sent['client_id'], 'other.apps.googleusercontent.com')
        listed = self.mgr.list_channels()['channels']
        self.assertEqual([(c['id'], c['client']) for c in listed], [('UCz', key)])
        self.login('UCa')                                               # the main app: no client
        self.assertEqual(self.mgr._index()['channels']['UCa']['client'], '')
        self.mgr.get_channel_info('UCz')                                # refreshing details keeps its app
        self.assertEqual(self.mgr._index()['channels']['UCz']['client'], key)
        self.mgr.remove_channel('UCz')
        self.assertFalse((self.data / 'youtube' / 'clients' / f'{key}.json').exists())
        with self.assertRaises(ValueError):
            self.mgr.get_auth_url(redirect, client=key)
        with self.assertRaises(ValueError):
            self.mgr.get_auth_url(redirect, client='../../x')

    def test_routes(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        youtube_uploader.attach(app, self.data, {})
        mgr = app.state.yt_manager
        mgr._store_login(FakeCreds('UCa'))
        mgr._store_login(FakeCreds('UCb'))
        client = TestClient(app)
        self.assertEqual(client.get('/youtube/channels').json()['active'], 'UCb')
        self.assertEqual(client.post('/youtube/channels/active', json={'id': 'UCa'}).json()['active'], 'UCa')
        self.assertEqual(client.post('/youtube/channels/active', json={'id': '../x'}).status_code, 400)
        left = client.post('/youtube/channels/remove', json={'id': 'UCa'}).json()
        self.assertEqual((left['active'], [c['id'] for c in left['channels']]), ('UCb', ['UCb']))
        self.assertEqual(client.post('/youtube/upload', json={'clip_id': 'abc123', 'channel': 'UCa'}).status_code, 400)
        ok = client.post('/youtube/auth-url-client', json={'secrets': {'client_id': 'third.apps.googleusercontent.com', 'client_secret': 's3'}})
        self.assertEqual(ok.status_code, 200)
        self.assertIn('client_id=third.apps.googleusercontent.com', ok.json()['url'])
        self.assertEqual(client.post('/youtube/auth-url-client', json={'secrets': {'web': {}}}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
