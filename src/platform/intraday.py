"""Separate intraday boundary. Daily bars are never accepted as minute bars."""

import numpy as np
import pandas as pd

MESSAGE = "Intraday-Prognose nicht verfügbar – geeignete Marktdaten fehlen."


def validate_minute_bars(frame, calendar):
    import exchange_calendars as xcals

    required = {"timestamp", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise ValueError(MESSAGE)
    stamps = pd.DatetimeIndex(frame.timestamp)
    if stamps.tz is None or not stamps.is_monotonic_increasing or stamps.has_duplicates:
        raise ValueError("Intraday benötigt eindeutige aufsteigende UTC-Zeitpunkte")
    stamps = stamps.tz_convert("UTC")
    cal = xcals.get_calendar(calendar)
    if any(not cal.is_trading_minute(t) for t in stamps):
        raise ValueError("Zeitpunkt außerhalb einer Handelsminute")
    if len(stamps) < 121:
        raise ValueError(MESSAGE)
    if any(cal.next_minute(a) != b for a, b in zip(stamps[:-1], stamps[1:])):
        raise ValueError("Minutendaten enthalten Lücken; kein vollständiges Trainingsfenster")
    values = frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    if (
        not np.isfinite(values.to_numpy()).all()
        or not values[["open", "high", "low", "close"]].gt(0).all().all()
        or not values.volume.ge(0).all()
    ):
        raise ValueError("Ungültige Intraday-OHLCV-Werte")
    if not (
        values.high.ge(values[["open", "close", "low"]].max(axis=1))
        & values.low.le(values[["open", "close", "high"]].min(axis=1))
    ).all():
        raise ValueError("Inkonsistente Intraday-OHLC-Werte")
    return stamps


def horizon_end(timestamp, minutes, calendar):
    import exchange_calendars as xcals

    if minutes not in (60, 120):
        raise ValueError("Nur 60 oder 120 Handelsminuten")
    cal = xcals.get_calendar(calendar)
    stamp = pd.Timestamp(timestamp)
    if stamp.tz is None or not cal.is_trading_minute(stamp):
        raise ValueError("Kein eindeutiger Vorhersagezeitpunkt während des Handels")
    future = cal.minutes_window(stamp, minutes + 1)[-1]
    if cal.minute_to_session(stamp) != cal.minute_to_session(future):
        raise ValueError("Horizont überschreitet die Handelssitzung")
    return future
