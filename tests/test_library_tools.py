"""My clips tools: delete from this computer, YouTube uploaded tag, upload several clips at once."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import youtube_uploader


class UploadTracking(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.yt = youtube_uploader.YouTubeManager(self.data)

    def tearDown(self):
        self.tmp.cleanup()

    def test_uploaded_clips_are_remembered(self):
        self.assertEqual(self.yt.clip_states(), {})
        self.yt._mark_uploaded('abc', 'vid1', 'https://youtube.com/shorts/vid1')
        again = youtube_uploader.YouTubeManager(self.data)          # survives a restart
        self.assertEqual(again.clip_states()['abc']['status'], 'uploaded')
        self.assertEqual(again.clip_states()['abc']['url'], 'https://youtube.com/shorts/vid1')

    def test_batch_uploads_one_after_another(self):
        for name in ('c1', 'c2'):
            (self.data / (name + '.mp4')).write_bytes(b'x')
        order = []

        def fake_worker(task_id, file_path, *rest):
            order.append(file_path.stem)
            self.yt.upload_tasks[task_id]['status'] = 'done'
            self.yt._mark_uploaded(file_path.stem, 'v' + file_path.stem, 'https://youtube.com/shorts/v' + file_path.stem)

        with mock.patch.object(self.yt, 'get_credentials', return_value=object()), \
                mock.patch.object(self.yt, '_upload_worker', side_effect=fake_worker):
            jobs = self.yt.start_batch([{'clip_id': 'c1'}, {'clip_id': 'c2'}, {'clip_id': 'missing'}, {'clip_id': '../etc'}])
            for _ in range(50):
                if len(order) == 2:
                    break
                time.sleep(.05)
        self.assertEqual(order, ['c1', 'c2'])
        self.assertEqual([bool(j.get('error')) for j in jobs], [False, False, True, True])
        states = self.yt.clip_states()
        self.assertEqual({states['c1']['status'], states['c2']['status']}, {'uploaded'})

    def test_batch_needs_a_connected_channel(self):
        with self.assertRaises(RuntimeError):
            self.yt.start_batch([{'clip_id': 'c1'}])


class DeleteClips(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient
            import app as studio
        except Exception as e:                      # noqa: BLE001
            raise unittest.SkipTest('TestClient unavailable: ' + str(e))
        cls.studio = studio
        cls.c = TestClient(studio.app, client=('127.0.0.1', 50000))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.patch = mock.patch.object(self.studio, 'DATA', self.data)
        self.patch.start()
        (self.data / 'src.mp4').write_bytes(b'x')
        (self.data / 'src.json').write_text('{}', encoding='utf-8')
        for name, extra in (('old', {'superseded_by': 'new'}), ('new', {})):
            (self.data / (name + '.json')).write_text(json.dumps({'source': 'src', 'result': {'status': 'done'}, **extra}), encoding='utf-8')
            for ext in ('mp4', 'srt', 'vtt'):
                (self.data / f'{name}.{ext}').write_bytes(b'x')

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_deletes_clip_and_its_older_versions_only(self):
        r = self.c.post('/clips/delete', json={'ids': ['new']}).json()
        self.assertEqual(sorted(r['deleted']), ['new', 'old'])
        self.assertEqual(sorted(p.name for p in self.data.iterdir()), ['src.json', 'src.mp4'])

    def test_never_deletes_a_source_video_or_odd_names(self):
        r = self.c.post('/clips/delete', json={'ids': ['src', '../src', '']}).json()
        self.assertEqual(r['deleted'], [])
        self.assertTrue((self.data / 'src.mp4').exists())
        self.assertEqual(self.c.post('/clips/delete', json={}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
