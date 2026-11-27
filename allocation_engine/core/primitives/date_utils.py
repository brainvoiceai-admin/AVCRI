"""Date iteration utilities."""
from datetime import timedelta


def daterange(start_date, end_date):
    """Yield every date from start_date through end_date inclusive."""
    d = start_date
    while d <= end_date:
        yield d
        d += timedelta(days=1)
