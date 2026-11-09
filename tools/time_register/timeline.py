"""Time on the Kyiv clock: minute strings, work intervals of a session, their cut, union and split by day."""
import sys
from collections import defaultdict
from datetime import datetime, time, timedelta

from .patterns import IDLE_MIN, KYIV


def local(epoch):
    return datetime.fromtimestamp(epoch, KYIV).strftime("%Y-%m-%d %H:%M")


def parse_minute(text, what):
    """Epoch of "YYYY-MM-DD HH:MM" Kyiv time; exits with a message on another format."""
    try:
        return int(datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=KYIV).timestamp())
    except ValueError:
        sys.exit(f"{what} {text!r} is not YYYY-MM-DD HH:MM")


def work_intervals(stamps):
    """Merge timestamps into [start, end] epoch-second pairs; a gap over IDLE_MIN starts a new pair."""
    idle = timedelta(minutes=IDLE_MIN)
    out = []
    for t in sorted(stamps):
        if out and t - out[-1][1] <= idle:
            out[-1][1] = t
        else:
            out.append([t, t])
    return [[int(a.timestamp()), int(b.timestamp())] for a, b in out if b > a]


def clip(intervals, lo, hi):
    return [[max(a, lo), min(b, hi)] for a, b in intervals if b > lo and a < hi]


def merge_intervals(intervals):
    merged = []
    for a, b in sorted(intervals):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def union_secs(intervals):
    return sum(b - a for a, b in merge_intervals(intervals))


def per_day(intervals):
    """Clock seconds per Kyiv day of the merged intervals (epoch arithmetic, so DST days are right)."""
    days = defaultdict(float)
    for a, b in merge_intervals(intervals):
        t = a
        while t < b:
            day = datetime.fromtimestamp(t, KYIV).date()
            cut = min(b, datetime.combine(day + timedelta(days=1), time.min, KYIV).timestamp())
            days[day] += cut - t
            t = cut
    return days
