#!/usr/bin/env python3
"""The osv-scanner result of a new project, by the rule of the standard (skill /new-project, tests/new-project-test.sh).

  python3 -I osv_summary.py <scan>.json pnpm-lock.yaml

One line per finding: `STOP`, `WARN` (HIGH only in dev dependencies: a warning in the summary, no stop) or `NOTE`, with
the package, its IDs and severity. Exit 0: nothing stops; 1: a MAL- id, CRITICAL, HIGH in a package that reaches
production, or a finding without severity; 2: a file can't be read, the lockfile is not pnpm's lockfile v9 or names a
package without a snapshot, or the scan holds no finding (the skill runs this only when the scanner reported one, so
the scanner's format changed).
"""
import json
import math
import re
import sys

HIGH = 7.0
CRITICAL = 9.0
LOCKFILE_VERSION = re.compile(r"^lockfileVersion: '?([^'\s]*)'?\s*$", re.M)
# The groups of an importer. The package manager and the config dependencies run too, so they count as production
PROD_GROUPS = ('dependencies', 'optionalDependencies', 'packageManagerDependencies', 'configDependencies')
DEV_GROUPS = ('devDependencies',)
# The groups of a snapshot that name the packages it needs
EDGE_GROUPS = ('dependencies', 'optionalDependencies')


def mapping_line(line):
    """(indent, key, value) of a `key: value` line of a block mapping, None for a list item, a comment or a blank line.
    pnpm quotes a key with ' when it needs quoting, and no quoted key of its holds `':`. An unquoted key may hold a
    colon (`localdir@file:vendor/localdir:`), so it ends at the first `: ` or at the colon that ends the line."""
    body = line.lstrip(' ')
    indent = len(line) - len(body)
    if body.startswith("'"):
        end = body.find("':", 1)
        if end < 0:
            return None
        key, rest = body[1:end], body[end + 2:]
    else:
        end = (body + ' ').find(': ')
        if end < 1 or body.startswith(('#', '-')):
            return None
        key, rest = body[:end], body[end + 1:]
    return indent, key, rest.strip().strip("'")


def node_of(name, version):
    """The snapshot key a dependency points at: `name@version(peers)`, or the target itself for an alias
    (`version: other@1.0.0`); None for a link to a local folder. A `file:` dependency is installed as a package of
    its own, with a snapshot (`name@file:vendor/x`)."""
    if version.startswith('link:'):
        return None
    head = version.split('(', 1)[0]
    # An alias names its target before any colon; an @ after one is part of a URL or a path
    at, colon = head.find('@', 1), head.find(':')
    return version if at > 0 and (colon < 0 or at < colon) else '%s@%s' % (name, version)


def lock_graph(text):
    """(production roots, dev roots, edges) of a pnpm-lock.yaml of lockfile v9, one document or several (pnpm 12 puts
    its own pin in the first), read by indent: pnpm writes two spaces a level and one key per line."""
    found = LOCKFILE_VERSION.findall(text)
    if not found or any(v != '9.0' for v in found):
        raise ValueError('not a pnpm lockfile v9 (lockfileVersion %s)' % (', '.join(found) or 'missing'))
    roots, edges = {'prod': set(), 'dev': set()}, {}
    section = group = name = node = None
    for line in text.splitlines():
        parsed = mapping_line(line)
        if parsed is None:
            continue
        indent, key, value = parsed
        if indent == 0:
            section = key
        elif section == 'importers' and indent == 4:
            group = key
        elif section == 'importers' and indent == 6:
            name = key
        elif section == 'importers' and indent == 8 and key == 'version' and group in PROD_GROUPS + DEV_GROUPS:
            target = node_of(name, value)
            if target:
                roots['dev' if group in DEV_GROUPS else 'prod'].add(target)
        elif section == 'snapshots' and indent == 2:
            node, group = key, None
            edges.setdefault(node, set())
        elif section == 'snapshots' and indent == 4:
            group = key
        elif section == 'snapshots' and indent == 6 and group in EDGE_GROUPS:
            target = node_of(key, value)
            if target:
                edges[node].add(target)
    # A root or an edge without a snapshot means the reader lost part of the file: the packages behind it would count
    # as dev-only or as unlisted, so a changed format stops here rather than shrinking what production reaches
    named = roots['prod'] | roots['dev'] | {t for targets in edges.values() for t in targets}
    dangling = sorted(t for t in named if t not in edges)
    if dangling:
        raise ValueError('pnpm-lock.yaml names %d package(s) without a snapshot, first %s'
                         % (len(dangling), dangling[0]))
    return roots['prod'], roots['dev'], edges


def reached(roots, edges):
    """(name, version) of every package the roots reach."""
    seen, todo = set(), list(roots)
    while todo:
        node = todo.pop()
        if node not in seen:
            seen.add(node)
            todo.extend(edges.get(node, ()))
    pairs = set()
    for node in seen:
        head = node.split('(', 1)[0]
        at = head.find('@', 1)  # a scope's @ stands first; the version's comes after the name
        if at > 0:
            pairs.add((head[:at], head[at + 1:]))
    return pairs


def lock_reach(text):
    """(packages production reaches, packages dev dependencies reach) of a pnpm-lock.yaml."""
    prod, dev, edges = lock_graph(text)
    return reached(prod, edges), reached(dev, edges)


def dev_only(reach, name, version):
    """Only dev dependencies reach this package. One that production reaches too, or that the lockfile doesn't list,
    counts as production."""
    in_prod, in_dev = reach
    return (name, version) in in_dev and (name, version) not in in_prod


def severity_of(group):
    try:
        severity = float(group.get('max_severity') or '')
    except ValueError:
        return None
    return severity if math.isfinite(severity) else None


def verdict(ids, severity, is_dev):
    if any(i.startswith('MAL-') for i in ids) or severity is None or severity >= CRITICAL:
        return 'STOP'
    if severity >= HIGH:
        return 'WARN' if is_dev else 'STOP'
    return 'NOTE'


def findings(scan, reach):
    """(verdict, line) of every finding of the scan."""
    found = []
    for result in scan.get('results') or []:
        for entry in result.get('packages') or []:
            name, version = entry['package']['name'], entry['package']['version']
            is_dev = dev_only(reach, name, version)
            for group in entry.get('groups') or [{}]:  # a package in the scan is a finding, grouped or not
                ids, severity = (group.get('ids') or []) + (group.get('aliases') or []), severity_of(group)
                word, score = verdict(ids, severity, is_dev), 'no severity' if severity is None else severity
                found.append((word, '%s %s@%s %s %s%s' % (word, name, version, ','.join(ids), score,
                                                          ' dev' if is_dev else '')))
    return found


def main(argv):
    if len(argv) != 2:
        print('usage: osv_summary.py <scan>.json pnpm-lock.yaml', file=sys.stderr)
        return 2
    where = argv[0]
    try:
        with open(argv[0], encoding='utf-8') as fh:
            scan = json.load(fh)
        where = argv[1]
        with open(argv[1], encoding='utf-8') as fh:
            reach = lock_reach(fh.read())
        where = argv[0]
        found = findings(scan, reach)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        # The skill shows this line and stops: the file and the kind of error, since a KeyError alone prints only a key
        print('osv_summary: %s: %s: %s' % (where, type(e).__name__, e), file=sys.stderr)
        return 2
    if not found:
        print('osv_summary: the scan holds no finding', file=sys.stderr)
        return 2
    print('\n'.join(line for _, line in found))
    return 1 if any(word == 'STOP' for word, _ in found) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
