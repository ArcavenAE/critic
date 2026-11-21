#!/usr/bin/env python3
# quota-per-mtok.py: quota points per million tokens, per account, window and UTC day.
# Definition: docs/analysis/glossary.md#quota-points-per-million-tokens. Every metric is diagnostic and never a gate (ADR-007;
# aae-orc .claude/rules/diagnostic-not-gate.md).
# Usage: quota-per-mtok.py SERIES_DIR DAILY_TOKENS_CSV CONFIG_HOME --classes CLASS[,CLASS...]
#   SERIES_DIR        marvel's persisted readings: one YYYY-MM-DD.jsonl per UTC day, one {key, sample} object per line, where key is
#                     the whole account key (harness, backend, credential_source, config_home) and sample carries cluster, window,
#                     used_percent, resets_at and at. Under the marvel home that is state/account-series.
#   DAILY_TOKENS_CSV  the ledger's daily-tokens.csv (ledger-s10-axes.py): cluster, day, uncached_input, write_5m, write_1h, read,
#                     output, total. The ledger reads one config home, so the file is one config home's tokens.
#   CONFIG_HOME       that config home, spelled as marvel keys it: '' for the harness's default directory, else the cleaned path.
#   --classes         the token classes the denominator counts, a comma list from uncached_input, write_5m, write_1h, read, output.
#                     There is no default in the code and the tool refuses to run without it: which classes draw quota is not
#                     public, and the choice is held for an operator ruling. The report names the classes it counted
#                     (denominator_classes).
# Series: one account key (the whole object, compared as a whole, never its rendering) and one window. Readings are ordered by
# their own time.
# Step: between two consecutive readings of a series.
#   same resets_at, used_percent not lower   points += the rise
#   same resets_at, used_percent lower        adds 0 points and is counted (falls)
#   resets_at differs                          a rollover: adds 0 points and is counted (rollovers). A reset followed by use above
#                                              the earlier reading is still a rollover, never a rise.
# A step belongs to the UTC day of its later reading, so the day's points undercount by what the rollover step would have added.
# Points are a percent of one login's own cap, so points of two accounts are never added: one cell per account, window and day,
# and no cluster figure.
# Pairing: a cell is computed only where its key's config_home equals CONFIG_HOME. Any other cell prints n/a, with a note.
# Shared home: the ledger reads one config home and cannot split a day's tokens between keys. On a cluster-day where more than one
# key on CONFIG_HOME has a reading, each of those keys prints n/a for that day (points_per_mtok and tokens_m) with the note
# "home shared by N keys". Their points are still reported, and the tokens are never divided between them. A key alone on the home
# that day is computed as above.
# Day row: points, tokens_m (the counted classes over a million), points_per_mtok, rollovers, falls. points_per_mtok is n/a, never 0,
# for a day with no step, no readings, no tokens or a config home that does not pair. Cell: n, median, p25, p75 of the days'
# points_per_mtok (linear interpolation between order statistics, position p*(n-1)); n/a in all three when n is 0. No mean.
# skipped_lines counts day-file lines that did not parse (a file cut short by a crash costs one reading, not the run).
# Grouping is by cluster and account key only: no reading or token is attributed to one seat.
import csv, datetime, json, re, sys

CLASS_NAMES = ('uncached_input', 'write_5m', 'write_1h', 'read', 'output')
USAGE = 'usage: quota-per-mtok.py SERIES_DIR DAILY_TOKENS_CSV CONFIG_HOME --classes CLASS[,CLASS...]'


def refuse(msg):
    sys.stderr.write('quota-per-mtok.py: %s\n%s\n' % (msg, USAGE))
    sys.exit(2)


def parse_args(argv):
    args = argv[1:]
    classes = None
    if '--classes' in args:
        i = args.index('--classes')
        if i + 1 >= len(args):
            refuse('--classes needs a comma list of token classes')
        classes = [c for c in args[i + 1].split(',') if c]
        args = args[:i] + args[i + 2:]
    if len(args) != 3:
        refuse('want SERIES_DIR DAILY_TOKENS_CSV CONFIG_HOME, got %d arguments' % len(args))
    if not classes:
        refuse('--classes is required. Which token classes the denominator counts is held for an operator ruling, '
               'so this tool carries no default. Choose from: %s' % ', '.join(CLASS_NAMES))
    bad = [c for c in classes if c not in CLASS_NAMES]
    if bad:
        refuse('unknown token class %s. Choose from: %s' % (', '.join(repr(b) for b in bad), ', '.join(CLASS_NAMES)))
    return args[0], args[1], args[2], classes


def when(s):
    s = re.sub(r'(\.\d{6})\d+', r'\1', s.replace('Z', '+00:00'))
    d = datetime.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d.astimezone(datetime.timezone.utc)


def label(key):
    """The marvel rendering of a key, used only to name a row for people; identity is the key object."""
    return ' '.join([key.get('harness') or '-', key.get('backend') or '-', key.get('credential_source') or '-',
                     key.get('config_home') or 'default-home'])


def read_series(series_dir):
    import os
    series, skipped = {}, 0
    for name in sorted(os.listdir(series_dir)):
        if not name.endswith('.jsonl'):
            continue
        with open(os.path.join(series_dir, name), errors='replace') as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    o = json.loads(line)
                    key, smp = o['key'], o['sample']
                    pct = float(smp['used_percent'])
                    at = when(smp['at'])
                    window, cluster = smp['window'], smp['cluster']
                    resets = when(smp['resets_at']) if smp.get('resets_at') else None
                    if not isinstance(key, dict) or isinstance(smp['used_percent'], bool):
                        raise ValueError('shape')
                except (ValueError, KeyError, TypeError):
                    skipped += 1
                    continue
                sk = (cluster, json.dumps(key, sort_keys=True), window)
                series.setdefault(sk, []).append((at, pct, resets, key))
    return series, skipped


def read_tokens(path, classes):
    tokens = {}
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            tokens[(r['cluster'], r['day'])] = sum(int(r[c]) for c in classes) / 1e6
    return tokens


def quantile(vals, p):
    pos = p * (len(vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def build(series_dir, tokens_csv, config_home, classes):
    series, skipped = read_series(series_dir)
    tokens = read_tokens(tokens_csv, classes)
    token_days = {}
    for cluster, day in tokens:
        token_days.setdefault(cluster, set()).add(day)
    # Keys with a reading on the token run's config home, per cluster and UTC day. The ledger reads one config home and cannot
    # split a day's tokens between two keys on it, so a cluster-day with more than one such key gets no ratio for any of them.
    home_keys = {}
    for (cluster, kj, _window), rows in series.items():
        if (rows[0][3].get('config_home') or '') == config_home:
            for at, _p, _r, _k in rows:
                home_keys.setdefault((cluster, at.strftime('%Y-%m-%d')), set()).add(kj)
    by_cluster = {}
    for (cluster, _kj, window), rows in sorted(series.items()):
        rows.sort(key=lambda r: r[0])
        key = rows[0][3]
        paired = (key.get('config_home') or '') == config_home
        days = {}

        def d(day):
            return days.setdefault(day, {'points': 0.0, 'steps': 0, 'rollovers': 0, 'falls': 0, 'seen': False})
        for at, _p, _r, _k in rows:
            d(at.strftime('%Y-%m-%d'))['seen'] = True
        for (_a_at, a_pct, a_res, _k1), (b_at, b_pct, b_res, _k2) in zip(rows, rows[1:]):
            x = d(b_at.strftime('%Y-%m-%d'))
            if a_res != b_res:
                x['rollovers'] += 1
            elif b_pct < a_pct:
                x['falls'] += 1
                x['steps'] += 1
            else:
                x['points'] += b_pct - a_pct
                x['steps'] += 1
        for day in token_days.get(cluster, ()):
            d(day)
        out_days, ratios = [], []
        for day in sorted(days):
            x = days[day]
            tm = tokens.get((cluster, day))
            ratio = 'n/a'
            sharers = len(home_keys.get((cluster, day), ())) if paired else 0
            shared = sharers > 1
            if paired and not shared and x['steps'] and tm:
                ratio = x['points'] / tm
                ratios.append(ratio)
            pts = x['points'] if x['seen'] else 'n/a'
            row = {'day': day, 'points': pts, 'tokens_m': tm if (paired and not shared and tm is not None) else 'n/a',
                   'points_per_mtok': ratio, 'rollovers': x['rollovers'], 'falls': x['falls']}
            if shared:
                row['note'] = 'home shared by %d keys, so the day\'s tokens cannot be split between them and no ratio is computed' % sharers
            out_days.append(row)
        ratios.sort()
        cell = {'days': out_days, 'n': len(ratios),
                'median': quantile(ratios, 0.5) if ratios else 'n/a',
                'p25': quantile(ratios, 0.25) if ratios else 'n/a',
                'p75': quantile(ratios, 0.75) if ratios else 'n/a'}
        if not paired:
            cell['note'] = 'the config home of this account key is not the config home of the token run, so no ratio is computed'
        acct = by_cluster.setdefault(cluster, {'by_account': {}})['by_account'].setdefault(label(key), {'by_window': {}})
        acct['by_window'][window] = cell
    return {'denominator_classes': classes, 'config_home': config_home, 'skipped_lines': skipped, 'by_cluster': by_cluster}


def main(argv):
    series_dir, tokens_csv, config_home, classes = parse_args(argv)
    json.dump(build(series_dir, tokens_csv, config_home, classes), sys.stdout, indent=1)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main(sys.argv)
