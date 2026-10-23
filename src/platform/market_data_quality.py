"""Audit source rows before the existing cleaner can drop, round or deduplicate them."""

import json
import math
from collections import Counter

import exchange_calendars as xcals
import pandas as pd

from src.preprocessing import clean_price_frame

from .forecast_contract import latest_available_session
from .market_data_provider import INSTRUMENTS, MarketDataError


def inspect_receipt(receipt):
    instrument = INSTRUMENTS[receipt.ticker]
    cal = xcals.get_calendar(instrument["calendar"])
    delay = max(900, receipt.declared_delay_seconds or 0)
    latest = latest_available_session(instrument["calendar"], receipt.received_at, delay)
    issues, valid, dates = [], [], []

    def issue(code, row=None, severity="error"):
        issues.append({"code": code, "row": row, "severity": severity})

    try:
        data = json.loads(receipt.payload)
        if (
            data["format"] != "yfinance_dataframe_projection_v1"
            or not isinstance(data["rows"], list)
            or len(data["rows"]) > 1000
        ):
            raise ValueError
        rows = data["rows"]
    except (ValueError, KeyError, TypeError):
        raise MarketDataError("response_shape", "Ungültiges Tagesdaten-Payload") from None

    for number, row in enumerate(rows):
        try:
            value = pd.Timestamp(row["Date"])
            if pd.isna(value):
                raise ValueError
            local = value.tz_convert(instrument["timezone"]) if value.tzinfo else value
            # A daily bar is exchange-local midnight, never UTC midnight guessed as a date.
            if local.time() != pd.Timestamp("00:00").time() or local.date() != value.date():
                raise ValueError
            day = pd.Timestamp(local.date())
        except (ValueError, TypeError, KeyError, AttributeError):
            issue("invalid_trade_date", number)
            continue
        if not receipt.requested_start <= day.date() <= receipt.requested_end:
            issue("outside_request", number)
            continue
        if not cal.is_session(day):
            issue("non_session", number)
            continue
        dates.append(day.date().isoformat())
        try:
            prices = [row[name] for name in ("Open", "High", "Low", "Close")]
            volume = row["Volume"]
            if not all(
                isinstance(v, (float, int))
                and not isinstance(v, bool)
                and math.isfinite(v)
                and v > 0
                for v in prices
            ):
                raise ValueError
            op, high, low, close = prices
            if high < max(op, low, close) or low > min(op, high, close):
                raise ValueError
            if (
                not isinstance(volume, (float, int))
                or isinstance(volume, bool)
                or not math.isfinite(volume)
                or volume < 0
                or volume >= 2**63
                or int(volume) != volume
            ):
                raise ValueError
            for name in ("Dividends", "Stock Splits"):
                action = row.get(name, 0)
                if (
                    not isinstance(action, (float, int))
                    or isinstance(action, bool)
                    or not math.isfinite(action)
                    or action < 0
                ):
                    raise ValueError
            if row.get("Stock Splits", 0) > 100 or row.get("Dividends", 0) > close:
                issue("corporate_action_anomaly", number)
                continue
        except (ValueError, TypeError, KeyError, OverflowError):
            issue("invalid_ohlcv", number)
            continue
        if day > latest:
            issue("incomplete_session", number, "warning")
            continue
        if volume == 0:
            issue("zero_volume", number, "warning")
        if row.get("Dividends", 0) or row.get("Stock Splits", 0):
            issue("corporate_action", number, "warning")
        valid.append((number, row, day.date().isoformat()))

    duplicates = {day for day, count in Counter(dates).items() if count > 1}
    for day in sorted(duplicates):
        issue("duplicate_session:" + day)
    valid = [(n, r, d) for n, r, d in valid if d not in duplicates]
    end = min(receipt.requested_end, latest.date())
    expected = (
        cal.sessions_in_range(receipt.requested_start, end)
        if receipt.requested_start <= end
        else []
    )
    missing = sorted(
        {pd.Timestamp(day).date().isoformat() for day in expected} - {d for _, _, d in valid}
    )
    if missing:
        issue("missing_sessions")
    if not valid:
        issue("no_completed_bars")
    stale = not valid or max(d for _, _, d in valid) < latest.date().isoformat()
    if stale:
        issue("stale_data", severity="warning")
    frame = (
        clean_price_frame(pd.DataFrame([r for _, r, _ in valid]), receipt.ticker)
        if valid
        else pd.DataFrame()
    )
    if not frame.empty:
        ordered = frame.sort_values("trade_date")
        for before, after in zip(ordered.to_dict("records"), ordered.to_dict("records")[1:]):
            ratio = after["close_price"] / before["close_price"]
            if not 0.5 <= ratio <= 1.5:
                issue("large_price_jump", severity="error")
    return frame, {
        "version": "daily-quality-v1",
        "status": "rejected" if any(i["severity"] == "error" for i in issues) else "accepted",
        "issues": issues,
        "received_rows": len(rows),
        "accepted_rows": len(frame),
        "missing_sessions": missing,
        "latest_completed_session": latest.date().isoformat(),
        "stale": stale,
        "delay_floor_seconds": delay,
    }
