"""Movie clipping: parts planned on pauses, the PART tag, and the analyze → make → upload routes (rendering and YouTube faked)."""
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import movies  # noqa: E402


class PlanTests(unittest.TestCase):
    def test_cuts_move_back_to_a_pause(self):
        self.assertEqual(movies.plan_parts(185, 60, quiet=[55, 58.5, 119, 170]),
                         [(0.0, 58.5), (58.5, 118.5), (118.5, 170), (170, 185)])

    def test_no_pauses_and_short_tail(self):
        self.assertEqual(movies.plan_parts(185, 60), [(0.0, 60.0), (60.0, 120.0), (120.0, 180.0), (180.0, 185)])
        self.assertEqual(movies.plan_parts(122, 60), [(0.0, 60.0), (60.0, 120.0)])          # a 2 s tail is dropped
        self.assertEqual(movies.plan_parts(40, 60), [(0.0, 40)])

    def test_range_and_limits(self):
        parts = movies.plan_parts(600, 60, start=30, end=300, quiet=[85, 140])
        self.assertEqual(parts[0], (30.0, 85))
        self.assertEqual(parts[-1][1], 300)
        self.assertTrue(all(z - a <= 60 for a, z in parts))
        with self.assertRaises(ValueError):
            movies.plan_parts(100, 60, start=99.5)
        with self.assertRaises(ValueError):
            movies.plan_parts(10 ** 6, 30)

    def test_times(self):
        self.assertEqual(movies.seconds('1:30', 'x'), 90)
        self.assertEqual(movies.seconds('0:01:30', 'x'), 90)
        self.assertEqual(movies.seconds('', 'x'), None)
        with self.assertRaises(Exception):
            movies.seconds('1:-3', 'x')


class TagTests(unittest.TestCase):
    def test_series_validation(self):
        self.assertIsNone(movies.series({}))
        s = movies.series({'series': {'part': 2, 'total': 9, 'title': 'KGF'}})
        self.assertEqual((s['part'], s['show_title'], s['show_part'], s['show_total'], s['next_hint']), (2, True, True, False, True))
        for bad in ({'part': 0}, {'part': 'x'}, {'part': 1, 'color': 'pink'}, 'nope'):
            with self.assertRaises(ValueError):
                movies.series({'series': bad})

    def test_events(self):
        s = movies.series({'series': {'part': 3, 'total': 9, 'title': 'KGF {Chapter} 2', 'color': '#16a34a', 'show_total': True}})
        text = '\n'.join(movies.events(s, 'blur', 1920, 1080, 1080, 1920, 58))
        self.assertIn('PART 3/9', text)
        self.assertIn('KGF (Chapter) 2', text)                        # ASS override braces are made safe
        self.assertIn('PART 4 NEXT', text)
        self.assertIn('&H004AA316&', text)                            # #16a34a as ASS blue-green-red
        last = '\n'.join(movies.events({**s, 'part': 9}, 'blur', 1920, 1080, 1080, 1920, 58))
        self.assertIn('THE END', last)
        bare = movies.events({**s, 'show_title': False, 'show_part': False, 'next_hint': False}, 'fill', 1920, 1080, 1080, 1920, 58)
        self.assertEqual(bare, [])

    def test_tag_sits_above_the_picture(self):
        self.assertEqual(round(movies.label_band('blur', 1920, 1080, 1080, 1920)), 656)
        self.assertEqual(round(movies.label_band('fill', 1920, 1080, 1080, 1920)), round(1920 * .22))


class RouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        # 20 s video whose sound pauses for 1.5 s every 7 s
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=320x180:r=10', '-f', 'lavfi', '-i',
                        "aevalsrc=exprs='0.4*sin(2*PI*440*t)*lt(mod(t\\,7)\\,5.5)':s=16000", '-t', '20', '-c:v', 'libx264',
                        '-preset', 'ultrafast', '-c:a', 'aac', '-shortest', str(self.data / 'abc123.mp4')], check=True)
        self.state, self.bodies, self.batches = {}, [], []
        app = self.app = FastAPI()

        def save(job, row):
            self.state[job] = {**self.state.get(job, {}), **row}

        def new_source(b):
            return '', self.data / (str(b['id']) + '.mp4')

        def export(body):
            ej = uuid.uuid4().hex
            self.bodies.append(body)
            self.state[ej] = {'status': 'done', 'file': ej}
            return {'job': ej}
        app.neon = {'save': save, 'new_source': new_source}
        outer = self

        class FakeYouTube:
            def _upload_channel(self, channel):
                return channel

            def get_config(self):
                return {'default_privacy': 'unlisted'}

            def start_batch(self, items, privacy, tags, description, channel=None):
                outer.batches.append((items, privacy, tags, channel))
                return [{'clip_id': i['clip_id'], 'task_id': 't' + str(n)} for n, i in enumerate(items)]
        app.state.yt_manager = FakeYouTube()
        movies.attach(app, self.data, self.state, lambda p: {'w': 320, 'h': 180, 'duration': 20.0}, export, {'pad': 4.0})

    def tearDown(self):
        self.tmp.cleanup()

    def wait(self, client, job):
        for _ in range(100):
            row = client.get('/movie/' + job).json()
            if row['status'] != 'running':
                return row
            time.sleep(.1)
        self.fail('still running')

    def test_analyze_make_upload(self):
        from fastapi.testclient import TestClient
        c = TestClient(self.app)
        self.assertEqual(c.post('/movie/analyze', json={'id': 'abc123', 'part_len': 50}).status_code, 400)
        self.assertEqual(c.post('/movie/analyze', json={'id': 'abc123', 'part_len': 30, 'start': '0:05', 'end': '0:02'}).status_code, 400)
        a = self.wait(c, c.post('/movie/analyze', json={'id': 'abc123', 'part_len': 30, 'title': 'Test'}).json()['job'])
        self.assertEqual(a['status'], 'done', a)
        self.assertEqual(a['count'], 1)
        self.assertGreaterEqual(a['pauses'], 2)
        self.assertEqual(c.post('/movie/make', json={'analysis': 'nope'}).status_code, 400)
        self.assertEqual(c.post('/movie/make', json={'analysis': a['id'], 'layout': 'stack'}).status_code, 400)
        self.assertEqual(c.post('/movie/make', json={'analysis': a['id'], 'parts': [99]}).status_code, 400)
        m = self.wait(c, c.post('/movie/make', json={'analysis': a['id'], 'title': 'My Movie', 'captions': False, 'color': '#16a34a',
                                                     'upload': True, 'privacy': 'private', 'channel': 'UCa'}).json()['job'])
        self.assertEqual(m['status'], 'done', m)
        body = self.bodies[-1]
        self.assertEqual((body['id'], body['start'], body['end'], body['layout'], body['hook_enabled'], body['captions']),
                         ('abc123', 0.0, 20.0, 'blur', False, False))
        self.assertEqual((body['series']['part'], body['series']['title'], body['series']['color']), (1, 'My Movie', '#16a34a'))
        self.assertEqual(body['title'], 'My Movie Part 1')
        items, privacy, tags, channel = self.batches[-1]
        self.assertEqual((items[0]['title'], privacy, channel), ('My Movie Part 1 #Shorts', 'private', 'UCa'))
        self.assertIn('Part 1 of 1', items[0]['description'])
        again = c.post('/movie/' + m['id'] + '/upload', json={'channel': 'UCb'}).json()
        self.assertEqual((len(again['jobs']), self.batches[-1][1], self.batches[-1][3]), (1, 'unlisted', 'UCb'))


if __name__ == '__main__':
    unittest.main()
