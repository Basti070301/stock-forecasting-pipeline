"""Descriptive monitoring of confirmed, paired future observations; no model selection."""

import exchange_calendars as xcals
import numpy as np
import pandas as pd

from .forecast_contract import latest_available_session, utc
from .holdout_evaluation import calibration_summary
from .research import metrics


def visible_outcome(outcome, now):
    return outcome is not None and all(
        not outcome.get(key) or utc(outcome[key]) <= utc(now)
        for key in ("outcome_at", "observed_at", "calculated_at")
    )


def confirmed_pairs(pipeline, now):
    store, protocol = pipeline.store, pipeline.protocol
    expected = {m["artifact_id"]: m for m in protocol["models"]}
    pairs = []
    if not pipeline.market.migrated():
        return pairs
    for marker in store.all("market_runs"):
        if (
            marker.get("kind") != "current_pair_commit"
            or marker.get("status") != "confirmed"
            or marker.get("source_kind") != "provider"
            or marker.get("protocol_hash") != pipeline.protocol_hash
            or utc(marker["saved_at"]) > utc(now)
        ):
            continue
        rows = [store.get("forecasts", identity) for identity in marker["forecast_ids"]]
        acceptance = (
            store.get("market_runs", marker["acceptance_id"])
            if marker.get("acceptance_id")
            else None
        )
        if (
            not acceptance
            or acceptance.get("kind") != "current_acceptance"
            or acceptance.get("protocol_hash") != pipeline.protocol_hash
        ):
            continue
        if (
            len(rows) != 2
            or any(r is None for r in rows)
            or {r["model_id"] for r in rows} != set(expected)
        ):
            continue
        if any(
            r.get("evaluation_scope") != "prospective_candidate"
            or r.get("source_kind") != "provider"
            or r.get("mode") != "current"
            or r.get("counterfactual_model_replay")
            or r.get("protocol_hash") != pipeline.protocol_hash
            or r["ticker"] != marker["ticker"]
            or r["model_version"] != expected[r["model_id"]]["model_version"]
            or r["artifact_sha256"] != expected[r["model_id"]]["artifact_sha256"]
            or utc(r["generated_at"]) > utc(marker["saved_at"])
            for r in rows
        ):
            continue
        if len({(r["decision_at"], r["data_version"], r["market_receipt_id"]) for r in rows}) != 1:
            continue
        receipt = store.get("market_observations", rows[0]["market_receipt_id"])
        committed = store.get("market_runs", "commit:" + rows[0]["market_receipt_id"])
        if (
            not receipt
            or receipt.get("source_kind") != "provider"
            or not committed
            or utc(committed["available_at"]) > utc(rows[0]["decision_at"])
            or utc(acceptance["accepted_at"]) > utc(rows[0]["decision_at"])
        ):
            continue
        cal = xcals.get_calendar(rows[0]["calendar"])
        if utc(marker["saved_at"]) >= cal.session_open(
            pd.Timestamp(rows[0]["target_session"])
        ) or any(
            utc(r["decision_at"]) <= utc(protocol["frozen_at"])
            or utc(marker["saved_at"]) - utc(r["decision_at"]) > pd.Timedelta(seconds=300)
            for r in rows
        ):
            continue
        pairs.append({"marker": marker, "forecasts": rows})
    return pairs


def prospective_summary(pipeline, now=None):
    now = utc(now or pipeline.clock())
    protocol, store = pipeline.protocol, pipeline.store
    pairs = confirmed_pairs(pipeline, now)
    t0 = min((utc(p["marker"]["saved_at"]) for p in pairs), default=None)
    by_ticker = {
        t: {
            "paired_forecasts": 0,
            "matured_pairs": 0,
            "positive": 0,
            "negative": 0,
            "eligible_sessions": 0,
            "coverage": 0.0,
        }
        for t in protocol["universe"]
    }
    rows = {m["artifact_id"]: [] for m in protocol["models"]}
    label_conflicts = 0
    for pair in pairs:
        ticker = pair["marker"]["ticker"]
        by_ticker[ticker]["paired_forecasts"] += 1
        outcomes = [store.get("outcomes", f["id"]) for f in pair["forecasts"]]
        if not all(visible_outcome(o, now) for o in outcomes):
            continue
        if (
            len(
                {
                    (o["actual"], o.get("market_evidence", {}).get("target_revision_id"))
                    for o in outcomes
                }
            )
            != 1
        ):
            label_conflicts += 1
            continue
        by_ticker[ticker]["matured_pairs"] += 1
        by_ticker[ticker]["positive" if outcomes[0]["actual"] else "negative"] += 1
        for f, o in zip(pair["forecasts"], outcomes):
            rows[f["model_id"]].append(
                {
                    "ticker": ticker,
                    "actual": o["actual"],
                    "probability": f["probability"],
                    "feature_session": f["feature_as_of"],
                }
            )
    if t0 is not None:
        from .market_data_provider import INSTRUMENTS

        for ticker, info in by_ticker.items():
            calendar = INSTRUMENTS[ticker]["calendar"]
            cal = xcals.get_calendar(calendar)
            start = latest_available_session(
                calendar, t0, max(900, pipeline.settings.market_delay_seconds or 0)
            )
            end = latest_available_session(
                calendar, now, max(900, pipeline.settings.market_delay_seconds or 0)
            )
            closed_windows = {
                day.date().isoformat()
                for day in cal.sessions_in_range(start, end)
                if t0 < cal.session_open(cal.next_session(day)) <= now
            }
            observed = {
                p["marker"]["feature_session"] for p in pairs if p["marker"]["ticker"] == ticker
            }
            info["eligible_sessions"] = len(closed_windows | observed)
            info["coverage"] = (
                info["paired_forecasts"] / info["eligible_sessions"]
                if info["eligible_sessions"]
                else 0.0
            )
    models = []
    revision_events = (
        [
            r
            for r in store.all("market_runs")
            if r.get("kind") == "current_outcome_revision"
            and utc(r["outcome"]["calculated_at"]) <= now
        ]
        if pipeline.market.migrated()
        else []
    )
    paired_ids = {f["id"] for pair in pairs for f in pair["forecasts"]}
    revised_outcomes = len(
        {r["forecast_id"] for r in revision_events if r["forecast_id"] in paired_ids}
    )

    def summarize(data, fixed):
        if not data:
            return {
                "n": 0,
                "metrics": None,
                "training_prevalence_baseline": None,
                "training_majority_baseline": None,
                "calibration": None,
            }
        target = np.array([r["actual"] for r in data], dtype=int)
        probability = np.array([r["probability"] for r in data], dtype=float)
        prior = fixed["training_positive_rate"]
        measured = metrics(target, probability)
        baseline = metrics(target, np.full(len(data), prior))
        return {
            "n": len(data),
            "metrics": measured,
            "training_prevalence_baseline": baseline,
            "training_majority_baseline": metrics(target, np.full(len(data), int(prior >= 0.5))),
            "brier_difference_vs_prevalence": measured["brier_score"] - baseline["brier_score"],
            "calibration": calibration_summary(target, probability),
        }

    for fixed in protocol["models"]:
        data = rows[fixed["artifact_id"]]
        models.append(
            {
                "model_id": fixed["artifact_id"],
                "model_version": fixed["model_version"],
                **summarize(data, fixed),
                "per_ticker": {
                    t: summarize([r for r in data if r["ticker"] == t], fixed)
                    for t in protocol["universe"]
                },
            }
        )
    minimum = protocol["minimum_observations"]
    sufficient = (
        t0 is not None
        and now >= t0 + pd.DateOffset(months=minimum["calendar_months_since_T0"])
        and all(
            i["matured_pairs"] >= minimum["per_ticker_per_model"]
            and i["positive"] >= minimum["positive_and_negative_per_ticker_minimum"]
            and i["negative"] >= minimum["positive_and_negative_per_ticker_minimum"]
            and i["coverage"] >= minimum["coverage_minimum"]
            for i in by_ticker.values()
        )
        and all(m["n"] >= minimum["per_model_total"] for m in models)
        and label_conflicts == 0
        and revised_outcomes == 0
    )
    return {
        "protocol_id": protocol["protocol_id"],
        "protocol_hash": pipeline.protocol_hash,
        "as_of": now.isoformat(),
        "T0": t0.isoformat() if t0 is not None else None,
        "status": "Ready for prespecified analysis" if sufficient else "Insufficient Evidence",
        "independent_validation": "not_started" if t0 is None else "ongoing_not_approved",
        "prospective_pairs": len(pairs),
        "matured_pairs": sum(i["matured_pairs"] for i in by_ticker.values()),
        "missing_outcome_pairs": len(pairs) - sum(i["matured_pairs"] for i in by_ticker.values()),
        "label_conflicts": label_conflicts,
        "known_outcome_revisions": revised_outcomes,
        "label_basis": "first_accepted; later revisions require explicit review before primary analysis",
        "instruments": by_ticker,
        "models": models,
        "minimum_observations": minimum,
        "primary_analysis_executed": False,
        "warning": "Deskriptiver Forschungsstatus; keine unabhängige Leistungsbestätigung, Profitabilität oder Modellfreigabe. Hauptauswertung und vorgegebener Block-Bootstrap bleiben ein ausdrücklicher späterer Schritt.",
    }


def current_status(pipeline, ticker=None):
    now = utc(pipeline.clock())
    try:
        pipeline.gate()
        blocked = None
    except ValueError as error:
        blocked = {"code": getattr(error, "code", "blocked"), "message": str(error)}
    summary = prospective_summary(pipeline, now)
    cycles = (
        [
            r
            for r in pipeline.store.all("market_runs")
            if r.get("kind") == "current_cycle"
            and r.get("protocol_hash") == pipeline.protocol_hash
            and utc(r["at"]) <= now
        ]
        if pipeline.market.migrated()
        else []
    )
    rows = []
    for symbol in [ticker] if ticker else pipeline.protocol["universe"]:
        receipts = pipeline.market.observations(symbol, now) if pipeline.market.migrated() else []
        latest = receipts[-1] if receipts else None
        forecasts = (
            [
                f
                for f in pipeline.store.all("forecasts")
                if f.get("protocol_hash") == pipeline.protocol_hash
                and f.get("ticker") == symbol
                and utc(f["generated_at"]) <= now
            ]
            if pipeline.market.migrated()
            else []
        )
        forecasts.sort(key=lambda f: utc(f["generated_at"]), reverse=True)
        stale, current_error = None, None
        if latest:
            try:
                frame, _ = pipeline.market.history(symbol, now)
                expected = latest_available_session(
                    latest["instrument"]["calendar"],
                    now,
                    max(900, latest["declared_delay_seconds"] or 0),
                )
                stale = frame.trade_date.max() != expected
            except ValueError as error:
                current_error = {"code": getattr(error, "code", "quality"), "message": str(error)}
        first = forecasts[0] if forecasts else None
        outcome = pipeline.store.get("outcomes", first["id"]) if first else None
        rows.append(
            {
                "ticker": symbol,
                "provider": latest["provider"] if latest else None,
                "source_kind": latest["source_kind"] if latest else "unavailable",
                "last_received_at": latest["received_at"] if latest else None,
                "last_confirmed_at": latest["available_at"] if latest else None,
                "quality": latest["quality"] if latest else None,
                "stale": stale,
                "error": current_error,
                "latest_forecast_at": first["generated_at"] if first else None,
                "forecast_scope": first["evaluation_scope"] if first else None,
                "outcome": outcome if visible_outcome(outcome, now) else None,
                "prospective_pairs": summary["instruments"][symbol]["paired_forecasts"],
                "matured_pairs": summary["instruments"][symbol]["matured_pairs"],
            }
        )
    return {
        "items": rows,
        "enabled": pipeline.settings.current_enabled,
        "auto_refresh": pipeline.settings.current_auto_refresh,
        "blocked": blocked,
        "prospective": summary,
        "last_cycle": max(cycles, key=lambda r: utc(r["at"]))["result"] if cycles else None,
        "note": "Kursstatus dieser Research-Datenbasis ist unabhängig vom historischen Preisdiagramm und vom Datenbankmodus.",
    }
