"""Go Live settings, logo/banner layer and stream-key safety (no network, no server)."""
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import golive


class GoLiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        (self.data / 'assets').mkdir()
        Image.new('RGBA', (200, 200), (0, 255, 0, 255)).save(self.data / 'assets' / 'logo1.png')

    def tearDown(self):
        self.tmp.cleanup()

    def test_shorts_and_landscape_sizes(self):
        s = golive.settings({'format': 'shorts', 'test': True}, self.data)
        self.assertEqual((s['width'], s['height']), (1080, 1920))
        s = golive.settings({'format': 'landscape', 'quality': 720, 'test': True, 'layout': 'stack'}, self.data)
        self.assertEqual((s['width'], s['height']), (1280, 720))
        self.assertEqual(s['layout'], 'blur')            # face-above-game is a vertical layout

    def test_shorts_crops_a_wide_video_to_fill(self):
        self.assertEqual(golive.settings({'test': True}, self.data)['layout'], 'fill')             # Shorts default: crop, not blur
        self.assertEqual(golive.settings({'format': 'landscape', 'test': True}, self.data)['layout'], 'blur')
        self.assertEqual(golive.crop_window(1920, 1080, 1080, 1920, 0), (0, 0, 606, 1080))         # left
        self.assertEqual(golive.crop_window(1920, 1080, 1080, 1920, .5), (657, 0, 606, 1080))      # centre
        self.assertEqual(golive.crop_window(1920, 1080, 1080, 1920, 1), (1314, 0, 606, 1080))      # right
        self.assertEqual(golive.crop_window(1080, 1920, 1920, 1080, .5), (0, 657, 1080, 606))      # tall video into landscape
        with self.assertRaises(ValueError):
            golive.settings({'test': True, 'crop': 150}, self.data)

    def test_test_cleanup_never_matches_a_downloaded_source(self):
        live = golive.Live(self.data, None, golive.settings({'test': True}, self.data), '', None, {}, None)
        self.assertTrue(golive.PREVIEW.match(live.id + '.mp4'))
        self.assertFalse(golive.PREVIEW.match(live.id + 'dl.mp4'))          # the video downloaded for a live

    def test_live_needs_key_and_rtmp_server(self):
        with self.assertRaises(ValueError):
            golive.settings({'platform': 'youtube', 'key': ''}, self.data)
        with self.assertRaises(ValueError):
            golive.settings({'platform': 'custom', 'server': 'http://x.com', 'key': 'k'}, self.data)
        s = golive.settings({'platform': 'youtube', 'key': 'abcd-1234'}, self.data)
        self.assertEqual(s['url'], 'rtmp://a.rtmp.youtube.com/live2/abcd-1234')

    def test_overlay_keeps_old_values_and_checks_files(self):
        o = golive.overlay_settings({'logo': 'logo1', 'banner_text': '  Hello   live ', 'logo_pos': 'bl'}, self.data)
        self.assertEqual(o['banner_text'], 'Hello live')
        o2 = golive.overlay_settings({'banner_bg': '#0000ff'}, self.data, o)
        self.assertEqual((o2['logo'], o2['logo_pos'], o2['banner_bg']), ('logo1', 'bl', '#0000ff'))
        with self.assertRaises(ValueError):
            golive.overlay_settings({'logo': 'missing1'}, self.data)
        with self.assertRaises(ValueError):
            golive.overlay_settings({'banner_bg': 'red'}, self.data)

    def test_layer_places_logo_and_banner(self):
        o = golive.overlay_settings({'logo': 'logo1', 'logo_pos': 'tr', 'banner_text': 'LIVE NOW', 'banner_bg': '#ff0000'}, self.data)
        im = golive.render_layer(o, 1080, 1920, self.data)
        self.assertEqual(im.getpixel((1080 - 43 - 50, 96 + 50))[:3], (0, 255, 0))             # logo top-right
        self.assertEqual(im.getpixel((60, int(1920 * .79)))[:3], (255, 0, 0))                    # banner above the Shorts buttons
        self.assertEqual(im.getpixel((540, 1900))[3], 0)                                         # bottom edge left clear
        hidden = golive.overlay_settings({'show_logo': False, 'show_banner': False}, self.data, o)
        self.assertIsNone(golive.render_layer(hidden, 1080, 1920, self.data))

    def test_stream_key_is_redacted(self):
        live = golive.Live(self.data, None, golive.settings({'platform': 'youtube', 'key': 'secret-key-9'}, self.data), '', None, {}, None)
        self.assertNotIn('secret-key-9', live._redact('rtmp://a.rtmp.youtube.com/live2/secret-key-9: I/O error'))
        self.assertNotIn('secret-key-9', str(live.status()))
        self.assertIn('Could not connect', golive.friendly('Connection refused', 'youtube'))


class YouTubeLiveTests(unittest.TestCase):
    """The automatic YouTube live: what is sent to the YouTube API (faked here, nothing goes online)."""

    def setUp(self):
        import json
        import youtube_uploader
        self.yu = youtube_uploader
        self.tmp = tempfile.TemporaryDirectory()
        self.mgr = youtube_uploader.YouTubeManager(Path(self.tmp.name))
        self.token = lambda scopes: self.mgr.token_file.write_text(json.dumps({'token': 't', 'refresh_token': 'r', 'client_id': 'c',
                                                                                'client_secret': 's', 'scopes': scopes}), encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_old_upload_only_login_needs_live_permission(self):
        self.token(['https://www.googleapis.com/auth/youtube.upload', 'https://www.googleapis.com/auth/youtube.readonly'])
        self.assertFalse(self.mgr.live_allowed())
        self.token(self.yu.SCOPES)
        self.assertTrue(self.mgr.live_allowed())
        self.assertIn(self.yu.LIVE_SCOPE, self.yu.SCOPES)

    def test_create_live_asks_youtube_for_an_auto_starting_broadcast(self):
        from unittest import mock
        self.token(self.yu.SCOPES)
        api = mock.MagicMock()
        api.liveStreams().insert().execute.return_value = {'id': 'S1', 'cdn': {'ingestionInfo': {'ingestionAddress': 'rtmp://a.rtmp.youtube.com/live2/', 'streamName': 'KEY-1'}}}
        api.liveBroadcasts().insert().execute.return_value = {'id': 'B1'}
        with mock.patch.object(self.mgr, 'get_credentials', return_value=object()), \
                mock.patch('googleapiclient.discovery.build', return_value=api):
            live = self.mgr.create_live('My live', 'desc', 'unlisted')
        self.assertEqual((live['server'], live['key'], live['broadcast_id']), ('rtmp://a.rtmp.youtube.com/live2', 'KEY-1', 'B1'))
        self.assertEqual(live['watch_url'], 'https://www.youtube.com/watch?v=B1')
        body = api.liveBroadcasts().insert.call_args.kwargs['body']
        self.assertEqual(body['status']['privacyStatus'], 'unlisted')
        self.assertTrue(body['contentDetails']['enableAutoStart'] and body['contentDetails']['enableAutoStop'])
        self.assertEqual(api.liveBroadcasts().bind.call_args.kwargs, {'id': 'B1', 'part': 'id,contentDetails', 'streamId': 'S1'})

    def test_end_live_completes_a_live_one_and_deletes_an_unused_one(self):
        from unittest import mock
        self.token(self.yu.SCOPES)
        api = mock.MagicMock()
        with mock.patch.object(self.mgr, '_youtube', return_value=api), mock.patch.object(self.mgr, 'live_status', return_value='live'):
            self.mgr.end_live('B1')
        api.liveBroadcasts().transition.assert_called_with(broadcastStatus='complete', id='B1', part='status')
        with mock.patch.object(self.mgr, '_youtube', return_value=api), mock.patch.object(self.mgr, 'live_status', return_value='ready'):
            self.mgr.end_live('B2')
        api.liveBroadcasts().delete.assert_called_with(id='B2')

    def test_readable_youtube_errors(self):
        self.assertIn('not turned on', self.yu.live_error(Exception('reason: liveStreamingNotEnabled')))
        self.assertIn('Allow live streaming', self.yu.live_error(Exception('insufficientPermissions')))

    def test_auto_youtube_needs_no_stream_key(self):
        s = golive.settings({'platform': 'youtube_auto', 'title': '  Big   live ', 'privacy': 'unlisted'}, Path(self.tmp.name))
        self.assertEqual((s['key'], s['title'], s['privacy']), ('', 'Big live', 'unlisted'))
        with self.assertRaises(ValueError):
            golive.settings({'platform': 'youtube_auto', 'privacy': 'everyone'}, Path(self.tmp.name))


class YouTubeLoginTests(unittest.TestCase):
    """Connect YouTube: the PKCE code verifier made for the login link must be sent back with the code (Google faked)."""

    def setUp(self):
        import json
        import youtube_uploader
        self.yu = youtube_uploader
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.mgr = youtube_uploader.YouTubeManager(self.data)
        self.mgr.save_secrets_data({'installed': {'client_id': 'cid.apps.googleusercontent.com', 'client_secret': 'sec',
                                                  'auth_uri': 'https://accounts.google.com/o/oauth2/auth', 'token_uri': 'https://oauth2.googleapis.com/token',
                                                  'redirect_uris': ['http://127.0.0.1:8770/youtube/oauth2callback']}})
        self.redirect = 'http://127.0.0.1:8771/youtube/oauth2callback'

    def tearDown(self):
        self.tmp.cleanup()

    def finish(self, state, restart=False):
        from unittest import mock
        from google_auth_oauthlib.flow import Flow
        from requests_oauthlib import OAuth2Session
        sent = {}

        class FakeCreds:
            def to_json(self):
                return '{"token": "t", "refresh_token": "r", "scopes": ["https://www.googleapis.com/auth/youtube"]}'

        def fake_google(session, token_url, **kw):          # what really goes to Google's token server
            sent.update(kw, redirect_uri=session.redirect_uri, token_url=token_url)
            return {'access_token': 't', 'token_type': 'Bearer'}
        mgr = self.yu.YouTubeManager(self.data) if restart else self.mgr
        with mock.patch.object(OAuth2Session, 'fetch_token', autospec=True, side_effect=fake_google), \
                mock.patch.object(Flow, 'credentials', new_callable=mock.PropertyMock, return_value=FakeCreds()), \
                mock.patch.object(self.yu.YouTubeManager, '_channel_of', return_value={'id': 'UCx', 'title': 'X'}):
            mgr.finish_auth_code('the-code', self.redirect, state)
        return sent

    def link(self):
        import base64
        import hashlib
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(self.mgr.get_auth_url(self.redirect)).query)
        verifier = self.mgr._pending()[q['state'][0]]['verifier']
        self.assertEqual(q['code_challenge_method'][0], 'S256')
        self.assertEqual(q['code_challenge'][0], base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='))
        return q['state'][0], verifier

    def test_callback_sends_the_matching_code_verifier(self):
        state, verifier = self.link()
        sent = self.finish(state)
        self.assertEqual((sent['code'], sent['code_verifier'], sent['redirect_uri']), ('the-code', verifier, self.redirect))
        self.assertTrue(self.mgr.live_allowed())                   # the new login carries the live permission
        self.assertNotIn(state, self.mgr._pending())               # used once, then forgotten

    def test_two_links_and_a_restart_in_between(self):
        first, v1 = self.link()
        second, v2 = self.link()
        self.assertEqual(self.finish(first, restart=True)['code_verifier'], v1)
        self.assertEqual(self.finish(None)['code_verifier'], v2)      # a code pasted by hand uses the newest link


if __name__ == '__main__':
    unittest.main()
