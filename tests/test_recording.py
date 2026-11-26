import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server_v2 as server
import stats_v5 as stats


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'recordings'
        self.output.mkdir()
        config = self.root / 'server_config.json'
        config.write_text(json.dumps({'output_dir': str(self.output)}))
        self.app_config = self.root / 'app_config.json'
        self.app_config.write_text(json.dumps(server.get_default_app_config()))
        self.settings = patch.multiple(server, CONFIG_PATH=config, APP_CONFIG_PATH=self.app_config)
        self.settings.start()
        self.addCleanup(self.settings.stop)
        server.active_trial_dirs.clear()
        server.active_trial_meta.clear()
        server.app.config['TESTING'] = True
        self.client = server.app.test_client()

    def test_evaluation_page_and_default_config(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'finishTrial', response.data)
        self.assertEqual(self.client.get('/app_config').json['selectionMode'], 'tds')

    def test_download_valid_recording(self):
        folder = self.output / 'trial'
        folder.mkdir()
        (folder / 'data.csv').write_text('time,value\n0,1\n')
        response = self.client.get('/download/trial/data.csv')
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'time,value\n0,1\n')
        self.assertIn('attachment', response.headers['Content-Disposition'])

    def test_download_rejects_parent_and_encoded_traversal(self):
        (self.root / 'private.txt').write_text('not public')
        for path in ['/download/../private.txt', '/download/%2e%2e/private.txt', '/download/trial/%2e%2e/%2e%2e/private.txt']:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_download_rejects_symlink_escape(self):
        private = self.root / 'private.txt'
        private.write_text('not public')
        (self.output / 'outside.txt').symlink_to(private)
        self.assertEqual(self.client.get('/download/outside.txt').status_code, 404)

    def test_download_rejects_directories_and_missing_files(self):
        (self.output / 'trial').mkdir()
        for path in ['/download/trial', '/download/missing.csv']:
            self.assertEqual(self.client.get(path).status_code, 404)

    def record_trial(self, mode='tds', trial_id='trial-1'):
        cfg = server.get_default_app_config()
        cfg['selectionMode'] = mode
        self.app_config.write_text(json.dumps(cfg))
        base = {'device_id':'test-device', 'trial_id':trial_id, 'subject_id':'dummy', 'sample_id':'sample', 'trial_no':'1'}
        events = [
            {'event':'start','t_sec':0},
            {'event':'slider','input_type':'slider','input_id':'slider_1','value':25,'t_sec':0},
            {'event':'button','input_type':'button','input_id':'button_1','value':1,'t_sec':0.2},
            {'event':'slider','input_type':'slider','input_id':'slider_1','value':75,'t_sec':0.5},
            {'event':'finish','t_sec':1},
        ]
        for event in events:
            response = self.client.post('/event', json={**base, **event})
            self.assertEqual(response.status_code, 200)
        return self.output / response.json['saved_folder']

    def test_recording_preserves_labels_metadata_and_duration(self):
        folder = self.record_trial()
        with (folder / 'data.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[1]['input_label'], 'scale 1')
        self.assertEqual(rows[2]['input_label'], 'item_1')
        metadata = server.active_trial_meta
        self.assertEqual(metadata, {})
        text = (folder / 'meta.txt').read_text()
        self.assertIn('duration_sec: 1', text)
        self.assertIn('subject_id: dummy', text)

    def test_repeated_trial_does_not_overwrite_previous_recording(self):
        first = self.record_trial()
        original = (first / 'data.csv').read_bytes()
        second = self.record_trial()
        self.assertNotEqual(first, second)
        self.assertEqual((first / 'data.csv').read_bytes(), original)

    def test_recorded_data_can_be_aggregated(self):
        self.record_trial()
        result = stats.run_stats(self.output, self.root / 'summary', sampling_rate_hz=2, save_config=False)
        self.assertEqual(result.n_trials, 1)
        mean_path = next((self.root / 'summary').rglob('TI_mean.csv'))
        with mean_path.open(encoding='cp932', newline='') as f:
            rows = list(csv.reader(f))
        self.assertTrue(any('25' in row for row in rows), rows)
        self.assertTrue(any('75' in row for row in rows), rows)
        self.assertTrue(list((self.root / 'summary').rglob('TDS_rate.csv')))


if __name__ == '__main__':
    unittest.main()
