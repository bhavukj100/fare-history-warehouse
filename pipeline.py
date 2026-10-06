"""Transactional SCD Type 2 fare history using Python and SQLite."""
import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

DDL = '''
CREATE TABLE IF NOT EXISTS fare_history (
 version_id INTEGER PRIMARY KEY, route TEXT NOT NULL, airline TEXT NOT NULL,
 fare_cents INTEGER NOT NULL CHECK(fare_cents >= 0), currency TEXT NOT NULL,
 valid_from TEXT NOT NULL, valid_to TEXT,
 CHECK(valid_to IS NULL OR valid_to > valid_from));
CREATE UNIQUE INDEX IF NOT EXISTS one_current_fare ON fare_history(route, airline) WHERE valid_to IS NULL;
CREATE TABLE IF NOT EXISTS loads(batch_id TEXT PRIMARY KEY, effective_at TEXT NOT NULL UNIQUE, digest TEXT NOT NULL);
'''

def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp must include a timezone')
    from datetime import timezone
    return parsed.astimezone(timezone.utc).isoformat(timespec='seconds')

def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    return conn

def load_batch(conn, batch):
    effective = timestamp(batch['effective_at'])
    rows = batch['fares']
    keys = set()
    for row in rows:
        key = (row['route'], row['airline'])
        if key in keys:
            raise ValueError('Duplicate natural key in batch')
        keys.add(key)
        if not isinstance(row['fare_cents'], int) or isinstance(row['fare_cents'], bool) or row['fare_cents'] < 0:
            raise ValueError('Fare must be nonnegative integer cents')
        import re
        if not re.fullmatch('[A-Z]{3}-[A-Z]{3}', row['route']) or not re.fullmatch('[A-Z0-9]{2}', row['airline']) or not re.fullmatch('[A-Z]{3}', row['currency']):
            raise ValueError('Invalid route, airline, or currency')
    payload = {'effective_at': effective, 'fares': sorted(rows, key=lambda r: (r['route'], r['airline']))}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    with conn:
        replay = conn.execute('SELECT digest FROM loads WHERE batch_id=?', (batch['batch_id'],)).fetchone()
        if replay:
            if replay['digest'] != digest:
                raise ValueError('Batch id reused with different content')
            return {'inserted': 0, 'changed': 0, 'unchanged': 0, 'replayed': True}
        last = conn.execute('SELECT MAX(effective_at) FROM loads').fetchone()[0]
        if last and effective <= last:
            raise ValueError('Out-of-order batch: rebuild history to apply older data')
        counts = {'inserted': 0, 'changed': 0, 'unchanged': 0, 'replayed': False}
        for row in rows:
            current = conn.execute('SELECT * FROM fare_history WHERE route=? AND airline=? AND valid_to IS NULL', (row['route'], row['airline'])).fetchone()
            if current and (current['fare_cents'], current['currency']) == (row['fare_cents'], row['currency']):
                counts['unchanged'] += 1
                continue
            if current:
                conn.execute('UPDATE fare_history SET valid_to=? WHERE version_id=?', (effective, current['version_id']))
                counts['changed'] += 1
            else:
                counts['inserted'] += 1
            conn.execute('INSERT INTO fare_history(route,airline,fare_cents,currency,valid_from) VALUES(?,?,?,?,?)', (row['route'], row['airline'], row['fare_cents'], row['currency'], effective))
        conn.execute('INSERT INTO loads VALUES(?,?,?)', (batch['batch_id'], effective, digest))
    return counts

def as_of(conn, at):
    at = timestamp(at)
    return [dict(r) for r in conn.execute('SELECT route, airline, fare_cents, currency, valid_from, valid_to FROM fare_history WHERE valid_from <= ? AND (valid_to > ? OR valid_to IS NULL) ORDER BY route, airline', (at, at))]

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='batches.json')
    parser.add_argument('--database', default='fares.db')
    parser.add_argument('--as-of', default='2026-01-02T00:00:00Z')
    args = parser.parse_args()
    conn = connect(args.database)
    try:
        for batch in json.loads(Path(args.input).read_text()):
            print(batch['batch_id'], load_batch(conn, batch))
        print(json.dumps(as_of(conn, args.as_of), indent=2))
    finally:
        conn.close()
