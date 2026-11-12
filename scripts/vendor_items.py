"""vendor_items.py: check 9b of scripts/verify.sh (split off for size). Run in the root of the tree under test.

vendor/items.tsv says where every vendored file came from, a line per pair "our file and its path in the source". One
format for the core and for the packs (ADR-007): path, class, repo, pin, upstream_path, license, sha256, upstream_blob,
reviewed, patch; a field with nothing to say is "-". Every file under skills/vendor-* and agents/vendor-* has a line
and every line names such a file; the pin is a full commit id; a patched file (the source at the pin plus a local
patch) names its patch file and the blob of the original, a derived one that blob, a verbatim one its own sha256, which
is the source's; every patch file under vendor/ is named by a line.
Prints a summary line, then a line per problem. Exit: 0 OK | 1 a problem.
"""
import glob, hashlib, os, re, sys
HEADER = 'path class repo pin upstream_path license sha256 upstream_blob reviewed patch'.split()
CLASSES = ('patched', 'verbatim', 'derived')
HEX40, REPO = re.compile(r'^[0-9a-f]{40}$'), re.compile(r'^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$')
fails, seen, patches = [], set(), set()
with open('vendor/items.tsv', encoding='utf-8') as fh:
    lines = [l for l in fh.read().split('\n') if l.strip()]
if not lines or lines[0].split('\t') != HEADER:
    fails.append('the first line must be the header: ' + ' '.join(HEADER))
    lines = lines[:1]
vendored = set(p for top in ('skills', 'agents') for g in glob.glob(top + '/vendor-*')
               for d, _, files in os.walk(g) for p in (os.path.join(d, f) for f in files if f != '.DS_Store'))
for no, line in enumerate(lines[1:], 2):
    c = line.split('\t')
    if len(c) != len(HEADER) or any(not x.strip() for x in c):
        fails.append('line %d: %d fields, the header has %d (nothing to say is "-")' % (no, len(c), len(HEADER)))
        continue
    r = dict(zip(HEADER, c))
    seen.add(r['path'])
    if r['path'] not in vendored:
        fails.append('line %d: %s is not a file under skills/vendor-* or agents/vendor-*' % (no, r['path']))
        continue
    if r['class'] not in CLASSES:
        fails.append('line %d: class "%s" is not one of %s' % (no, r['class'], ', '.join(CLASSES)))
    if not HEX40.match(r['pin']) or not REPO.match(r['repo']):
        fails.append('line %d: repo is owner/name and pin a full commit id (40 hex)' % no)
    if r['class'] == 'patched':
        patches.add(r['patch'])
        if not r['patch'].startswith('vendor/') or not os.path.isfile(r['patch']):
            fails.append('line %d: a patched file names its patch file under vendor/' % no)
    elif r['patch'] != '-':
        fails.append('line %d: only a patched file has a patch' % no)
    if r['class'] == 'verbatim':
        with open(r['path'], 'rb') as fh:
            if hashlib.sha256(fh.read()).hexdigest() != r['sha256']:
                fails.append('line %d: sha256 is not the file\'s: a verbatim file equals its source' % no)
    elif r['class'] in CLASSES and not HEX40.match(r['upstream_blob']):
        fails.append('line %d: a %s file names the blob of the original at the pin (40 hex)' % (no, r['class']))
fails.extend('%s: a vendored file with no line' % p for p in sorted(vendored - seen))
fails.extend('%s: a patch file no line names' % p for p in sorted(set(glob.glob('vendor/*/patches/*')) - patches))
print('%d line(s) for %d vendored file(s), %d patch file(s)' % (len(lines) - 1, len(vendored), len(patches)))
for f in fails:
    print(f)
sys.exit(1 if fails else 0)
