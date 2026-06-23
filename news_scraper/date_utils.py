from datetime import date, datetime, timedelta, timezone
from calendar import timegm

IST = timezone(timedelta(hours=5, minutes=30))


def to_ist_date(struct_time_utc):
    """Convert a feedparser UTC struct_time (e.g. entry.published_parsed) to an IST date."""
    if struct_time_utc is None:
        return None
    utc_dt = datetime.fromtimestamp(timegm(struct_time_utc), tz=timezone.utc)
    return utc_dt.astimezone(IST).date()


def matches_target_date(entry, target_date_str):
    """target_date_str: 'YYYY-MM-DD'. Returns True if entry's IST publish date matches."""
    target = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    published = getattr(entry, "published_parsed", None)
    ist_date = to_ist_date(published)
    return ist_date == target
