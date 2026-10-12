"""NYSE's published 2026–2028 equity calendar; unknown years fail closed.

Source, verified 2026-10-12: https://www.nyse.com/trade/hours-calendars
Special unscheduled closures still require an operator/calendar update.
"""

from datetime import datetime, time
from zoneinfo import ZoneInfo

NYSE = ZoneInfo('America/New_York')
HOLIDAYS = {
    2026: {'01-01','01-19','02-16','04-03','05-25','06-19','07-03','09-07','11-26','12-25'},
    2027: {'01-01','01-18','02-15','03-26','05-31','06-18','07-05','09-06','11-25','12-24'},
    2028: {'01-17','02-21','04-14','05-29','06-19','07-04','09-04','11-23','12-25'},
}
EARLY_CLOSE = {'2026-11-27','2026-12-24','2027-11-26','2028-07-03','2028-11-24'}


def session_bounds(day):
    if day.year not in HOLIDAYS or day.weekday() >= 5 or day.strftime('%m-%d') in HOLIDAYS[day.year]:
        return None
    return (datetime.combine(day, time(9, 30), NYSE),
            datetime.combine(day, time(13 if day.isoformat() in EARLY_CLOSE else 16), NYSE))


def market_open(now):
    local = now.astimezone(NYSE)
    bounds = session_bounds(local.date())
    return bool(bounds and bounds[0] <= local < bounds[1])
