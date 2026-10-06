import copy
import json
import unittest
from pathlib import Path
from pipeline import connect, load_batch, as_of

class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(':memory:')
        self.batches = json.loads(Path('batches.json').read_text())
    def tearDown(self):
        self.conn.close()
    def test_history_boundary_and_replay(self):
        for batch in self.batches:
            load_batch(self.conn, batch)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM fare_history').fetchone()[0], 5)
        old = as_of(self.conn, '2026-01-01T23:59:59Z')
        new = as_of(self.conn, '2026-01-02T00:00:00Z')
        self.assertEqual(next(r['fare_cents'] for r in old if r['airline'] == 'DL'), 25000)
        self.assertEqual(next(r['fare_cents'] for r in new if r['airline'] == 'DL'), 23000)
        self.assertTrue(load_batch(self.conn, self.batches[0])['replayed'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM fare_history WHERE valid_to IS NULL').fetchone()[0], 3)
    def test_conflict_rejected_without_changes(self):
        load_batch(self.conn, self.batches[0])
        altered = copy.deepcopy(self.batches[0])
        altered['fares'][0]['fare_cents'] += 1
        with self.assertRaises(ValueError):
            load_batch(self.conn, altered)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM loads').fetchone()[0], 1)
    def test_late_and_duplicate_batches_rejected(self):
        load_batch(self.conn, self.batches[0])
        altered = copy.deepcopy(self.batches[0])
        altered['batch_id'] = 'late'
        with self.assertRaises(ValueError):
            load_batch(self.conn, altered)
        altered = copy.deepcopy(self.batches[1])
        altered['fares'].append(altered['fares'][0])
        with self.assertRaises(ValueError):
            load_batch(self.conn, altered)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM loads').fetchone()[0], 1)
    def test_invalid_fare_and_timezone(self):
        for field, value in [('fare_cents', -1), ('currency', 'bad')]:
            altered = copy.deepcopy(self.batches[0])
            altered['fares'][0][field] = value
            with self.assertRaises(ValueError):
                load_batch(self.conn, altered)
        with self.assertRaises(ValueError):
            as_of(self.conn, '2026-01-01')

if __name__ == '__main__':
    unittest.main()
