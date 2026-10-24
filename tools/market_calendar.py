"""Reviewed exchange holidays, separate from data availability and civil workdays."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def sessions(spec):
    if spec.get('schema') != 'ql.exchange-calendar/1' or spec.get('timezone') != 'Asia/Shanghai':
        raise ValueError('calendar_schema')
    year = spec['year']
    if type(year) is not int or not 2000 <= year <= 2100:
        raise ValueError('calendar_year')
    closed = set()
    for start, end in spec['holiday_ranges']:
        a, b = date.fromisoformat(start), date.fromisoformat(end)
        if a.year != year or b.year != year or a > b:
            raise ValueError('calendar_holiday_range')
        closed.update(a + timedelta(days=n) for n in range((b-a).days+1))
    for value in spec['extra_closed_dates']:
        d = date.fromisoformat(value)
        if d.year != year:
            raise ValueError('calendar_exception_year')
        closed.add(d)
    d, end = date(year, 1, 1), date(year, 12, 31)
    result = []
    while d <= end:
        if d.weekday() < 5 and d not in closed:
            result.append(d.isoformat())
        d += timedelta(days=1)
    return result


def window(spec, start, end):
    days = sessions(spec)
    if start not in days or end not in days or start > end:
        raise ValueError('interval_outside_exchange_sessions')
    return {'version': 'exchange-holidays-2026/review-20261024',
            'source_url': spec['sources'][0], 'coverage_start': start,
            'coverage_end': end, 'sessions': [d for d in days if start <= d <= end]}


def latest_completed(spec, now):
    """15:00 is session close, NOT a promise that NAVs have been disclosed."""
    if now.tzinfo is None:
        raise ValueError('timezone_required')
    local = now.astimezone(ZoneInfo('Asia/Shanghai'))
    if local.year != spec['year']:
        raise ValueError('unreviewed_year')
    eligible = [d for d in sessions(spec) if d < local.date().isoformat() or
                (d == local.date().isoformat() and local.time() >= time(15))]
    if not eligible:
        raise ValueError('no_completed_session_in_calendar')
    return eligible[-1]
