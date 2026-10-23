"""Offline fixture tests only: no real Yahoo requests and no current model forecasts."""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import exchange_calendars as xcals
import pandas as pd
import pytest
from sqlalchemy import inspect
from yfinance.exceptions import YFRateLimitError

from src.platform.config import Settings
from src.platform.market_data import MarketIngestion, main
from src.platform.market_data_provider import (
    INSTRUMENTS,
    MarketDataError,
    MarketReceipt,
    YahooDailyProvider,
    encode_frame,
    stamp,
)
from src.platform.market_data_quality import inspect_receipt
from src.platform.market_data_store import MarketRepository
from src.platform.store import Store


class Clock:
    def __init__(self, value="2026-10-19T21:00:00+00:00"):
        self.value = datetime.fromisoformat(value)

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += timedelta(seconds=seconds)


def frame(days=("2026-10-15", "2026-10-16", "2026-10-19"), ticker="AAPL", close=101):
    return pd.DataFrame(
        {
            "Open": 100.0,
            "High": 110.0,
            "Low": 90.0,
            "Close": float(close),
            "Volume": 1000,
            "Dividends": 0.0,
            "Stock Splits": 0.0,
        },
        index=pd.DatetimeIndex(days).tz_localize(INSTRUMENTS[ticker]["timezone"]),
    )


def receipt(clock, prices=None, ticker="AAPL", **changes):
    prices = frame(ticker=ticker) if prices is None else prices
    fields = dict(
        ticker=ticker,
        source_kind="fixture",
        requested_start=date(2026, 10, 15),
        requested_end=date(2026, 10, 19),
        request_started_at=clock() - timedelta(seconds=1),
        received_at=clock(),
        payload=encode_frame(prices),
        library_version="fixture-v1",
    )
    return MarketReceipt(**(fields | changes))


@pytest.fixture
def environment(tmp_path):
    settings = Settings(
        _env_file=None,
        runtime_dir=tmp_path,
        market_enabled=True,
        market_rights_accepted=True,
        market_rights_reference="offline-test-only-no-provider-permission",
        market_min_interval_seconds=1,
    )
    store = Store(settings)
    store.migrate()
    clock = Clock()
    repository = MarketRepository(store, clock)
    repository.migrate()
    return settings, store, clock, repository


def persist(repo, clock, observation):
    clock.sleep(1)
    return repo.persist(observation)


def test_explicit_additive_migration_keeps_existing_records(tmp_path):
    store = Store(Settings(_env_file=None, runtime_dir=tmp_path))
    repo = MarketRepository(store)
    assert not repo.migrated()
    with pytest.raises(MarketDataError, match="Plattformmigration"):
        repo.migrate()
    store.migrate()
    assert not inspect(store.engine).has_table("si_market_observations")
    store.add("forecasts", {"reference": "untouched"}, "original")
    before = store.get("forecasts", "original")
    repo.migrate()
    marker = store.get("schema_versions", "v4")
    repo.migrate()
    assert marker == store.get("schema_versions", "v4")
    assert store.get("forecasts", "original") == before
    assert repo.migrated()


@pytest.mark.parametrize("ticker", INSTRUMENTS)
def test_provider_uses_shared_daily_request_and_real_request_times(environment, ticker):
    settings, _, clock, _ = environment
    client = Mock()

    def response(**kwargs):
        clock.sleep(2)
        return frame(ticker=ticker)

    client.history.side_effect = response
    provider = YahooDailyProvider(settings, Mock(return_value=client), clock)
    result = provider.fetch(ticker, date(2026, 10, 15), date(2026, 10, 19))
    assert result.received_at - result.request_started_at == timedelta(seconds=2)
    assert result.received_at.tzinfo == timezone.utc
    assert result.provider_published_at is None
    assert result.declared_delay_seconds is None
    client.history.assert_called_once_with(
        interval="1d",
        auto_adjust=True,
        actions=True,
        start="2026-10-15",
        end="2026-10-20",
        timeout=15,
        keepna=True,
        repair=False,
        prepost=False,
        raise_errors=True,
    )
    assert inspect_receipt(result)[1]["status"] == "accepted"


@pytest.mark.parametrize(
    "flag", ["market_enabled", "market_rights_accepted", "market_rights_reference"]
)
def test_disabled_or_unproven_rights_never_contact_provider(environment, flag):
    settings, _, clock, _ = environment
    settings = settings.model_copy(update={flag: "" if flag.endswith("reference") else False})
    factory = Mock()
    with pytest.raises(MarketDataError) as error:
        YahooDailyProvider(settings, factory, clock).fetch(
            "AAPL", date(2026, 10, 15), date(2026, 10, 19)
        )
    assert error.value.code == "access_blocked"
    factory.assert_not_called()


@pytest.mark.parametrize(
    "problem,code,retry",
    [
        (TimeoutError("secret-url"), "transport", True),
        (YFRateLimitError(), "rate_limit", False),
        (ValueError("secret-token"), "provider", False),
    ],
)
def test_provider_error_is_safe(environment, problem, code, retry):
    settings, _, clock, _ = environment
    client = Mock()
    client.history.side_effect = problem
    with pytest.raises(MarketDataError) as error:
        YahooDailyProvider(settings, Mock(return_value=client), clock).fetch(
            "AAPL", date(2026, 10, 15), date(2026, 10, 19)
        )
    assert error.value.code == code
    assert error.value.retryable is retry
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"request_started_at": "2026-10-19T22:00:00+00:00"},
        {"received_at": "2026-10-19T21:00:00"},
        {"requested_end": "2026-10-01"},
        {"requested_start": "2020-01-01"},
    ],
)
def test_receipt_rejects_ambiguous_times_and_ranges(environment, changes):
    with pytest.raises(ValueError):
        receipt(environment[2], **changes)


@pytest.mark.parametrize(
    "column,value",
    [
        ("Open", 0),
        ("Close", -1),
        ("High", 99),
        ("Low", 102),
        ("Volume", -1),
        ("Volume", 0.5),
        ("Volume", float("nan")),
        ("Close", float("inf")),
        ("Stock Splits", -1),
        ("Stock Splits", 101),
        ("Dividends", 200),
    ],
)
def test_invalid_ohlcv_is_audited_before_cleaner(environment, column, value):
    data = frame().astype(float)
    data.loc[data.index[1], column] = value
    _, quality = inspect_receipt(receipt(environment[2], data))
    assert quality["status"] == "rejected"
    assert quality["accepted_rows"] == 2
    assert "2026-10-16" in quality["missing_sessions"]


def test_duplicate_sessions_not_silently_deduplicated(environment):
    data = pd.concat([frame(), frame().iloc[:1]])
    _, quality = inspect_receipt(receipt(environment[2], data))
    assert quality["status"] == "rejected"
    assert quality["accepted_rows"] == 2
    assert any(i["code"].startswith("duplicate_session") for i in quality["issues"])


def test_gaps_weekends_and_wrong_midnight_offsets(environment):
    data = frame(("2026-10-15", "2026-10-17", "2026-10-19"))
    _, quality = inspect_receipt(receipt(environment[2], data))
    assert quality["status"] == "rejected"
    assert "2026-10-16" in quality["missing_sessions"]
    assert any(i["code"] == "non_session" for i in quality["issues"])
    data.index = data.index.tz_convert("UTC").normalize()
    assert inspect_receipt(receipt(environment[2], data))[1]["status"] == "rejected"


def test_local_date_preserved_for_german_dst_offset(environment):
    output, quality = inspect_receipt(
        receipt(environment[2], frame(ticker="SAP.DE"), ticker="SAP.DE")
    )
    assert output.trade_date.astype(str).tolist() == ["2026-10-15", "2026-10-16", "2026-10-19"]
    assert quality["status"] == "accepted"
    assert stamp("2026-10-19T23:00:00+02:00") == stamp(environment[2]())


def test_forming_session_excluded_and_zero_volume_explicit(environment):
    clock = Clock("2026-10-19T18:00:00+00:00")
    data = frame()
    data.loc[data.index[0], "Volume"] = 0
    output, quality = inspect_receipt(receipt(clock, data))
    assert len(output) == 2
    assert quality["status"] == "accepted"
    assert {i["code"] for i in quality["issues"]} >= {"incomplete_session", "zero_volume"}
    assert quality["latest_completed_session"] == "2026-10-16"


def test_holiday_and_different_exchange_closes(environment):
    # US Independence Day observed July 3; Xetra is open.
    clock = Clock("2026-07-03T17:00:00+00:00")
    for ticker, accepted in [("AAPL", False), ("SAP.DE", True)]:
        result = receipt(
            clock,
            frame(("2026-07-03",), ticker),
            ticker=ticker,
            requested_start="2026-07-03",
            requested_end="2026-07-03",
        )
        assert (inspect_receipt(result)[1]["status"] == "accepted") is accepted


def test_stale_and_empty_are_visible(environment):
    observation = receipt(
        environment[2], frame(("2026-10-15", "2026-10-16")), requested_end="2026-10-16"
    )
    assert inspect_receipt(observation)[1]["stale"] is True
    empty = receipt(environment[2], frame().iloc[:0])
    assert inspect_receipt(empty)[1]["status"] == "rejected"


def test_revision_recurrence_and_observation_times_survive_restart(environment):
    settings, store, clock, repo = environment
    first = receipt(clock)
    assert persist(repo, clock, first)["new_revisions"] == 3
    first_available = clock()
    assert repo.persist(first)["new_revisions"] == 0
    assert repo.persist(first)["new_observation"] is False
    clock.sleep(60)
    revised = receipt(clock, frame(close=102))
    assert persist(repo, clock, revised)["new_revisions"] == 3
    second_available = clock()
    clock.sleep(60)
    recurrence = receipt(clock)
    assert persist(repo, clock, recurrence)["new_revisions"] == 0
    # A/B/A: latest observation, not revision creation order, selects the active version.
    assert repo.history("AAPL", first_available)[0].close_price.tolist() == [101] * 3
    assert repo.history("AAPL", second_available)[0].close_price.tolist() == [102] * 3
    assert repo.history("AAPL", clock())[0].close_price.tolist() == [101] * 3
    versions = repo.revisions("AAPL", clock())
    assert len(versions) == 6
    original = [r for r in versions if r["bar"]["close_price"] == 101]
    assert all(r["observations"] == 2 for r in original)
    assert all(r["first_seen_at"] == first.model_dump(mode="json")["received_at"] for r in original)
    assert all(
        r["last_seen_at"] == recurrence.model_dump(mode="json")["received_at"] for r in original
    )
    store.engine.dispose()
    fresh = MarketRepository(Store(settings), clock)
    assert fresh.history("AAPL", clock())[0].close_price.tolist() == [101] * 3
    assert len(fresh.revisions("AAPL", first_available)) == 3
    assert len(fresh.store.all("forecasts")) == 0


def test_receipt_and_commit_are_both_required_for_asof(environment):
    _, store, clock, repo = environment
    observation = receipt(clock)
    received = clock()
    persist(repo, clock, observation)
    with pytest.raises(MarketDataError):
        repo.history("AAPL", received)
    with pytest.raises(MarketDataError):
        repo.history("AAPL", "2026-10-18T21:00:00+00:00")
    # A freshly queried old price cannot retroactively become available on its market date.
    assert repo.history("AAPL", clock())[1]["provider_published_at"] is None
    assert len(store.all("market_observations")) == 1


def test_newest_bad_vintage_quarantined_and_no_fallback(environment):
    _, store, clock, repo = environment
    persist(repo, clock, receipt(clock))
    clock.sleep(30)
    invalid = receipt(clock, frame().iloc[1:])
    result = persist(repo, clock, invalid)
    assert result["quality"]["status"] == "rejected"
    with pytest.raises(MarketDataError) as error:
        repo.history("AAPL", clock())
    assert error.value.code == "quality"
    assert store.get("market_observations", result["receipt_id"])["payload"] == invalid.payload


def test_receipt_identity_conflict_and_invalid_payload_retained(environment):
    _, store, clock, repo = environment
    observation = receipt(clock)
    persist(repo, clock, observation)
    changed = receipt(clock, frame(close=103), receipt_id=observation.receipt_id)
    with pytest.raises(MarketDataError) as error:
        repo.persist(changed)
    assert error.value.code == "immutable_conflict"
    malformed = receipt(clock, payload="{bad-json")
    result = persist(repo, clock, malformed)
    assert result["quality"]["status"] == "rejected"
    assert store.get("market_observations", result["receipt_id"])["payload"] == "{bad-json"


def test_forecast_features_reuse_original_contract_without_predictions(environment):
    _, store, clock, repo = environment
    clock.value = datetime(2026, 10, 22, 21, tzinfo=timezone.utc)
    days = xcals.get_calendar("XNYS").sessions_in_range("2025-10-23", "2026-10-22")
    data = frame(days)
    # Deterministic, nonconstant test history; source_kind simulates provider metadata ONLY here.
    data["Close"] = [100 + (i % 7) / 10 for i in range(len(data))]
    observation = receipt(
        clock,
        data,
        requested_start="2025-10-23",
        requested_end="2026-10-22",
        source_kind="provider",
        declared_delay_seconds=900,
    )
    persist(repo, clock, observation)
    clock.sleep(1)
    snapshot = repo.feature_snapshot("AAPL", clock())
    assert snapshot.feature_as_of == date(2026, 10, 22)
    assert snapshot.target_session == date(2026, 10, 23)
    assert len(snapshot.features) == 6
    assert snapshot.source.kind == "stored_market_data"
    assert store.all("forecasts") == []


@pytest.mark.parametrize(
    "source,delay,code", [("fixture", 900, "fixture"), ("provider", None, "delay_unknown")]
)
def test_feature_input_rejects_fixture_or_unknown_delay(environment, source, delay, code):
    _, _, clock, repo = environment
    persist(repo, clock, receipt(clock, source_kind=source, declared_delay_seconds=delay))
    with pytest.raises(MarketDataError) as error:
        repo.feature_snapshot("AAPL", clock())
    assert error.value.code == code


def test_global_lease_rejects_parallel_import_and_only_owner_releases(environment):
    _, _, _, repo = environment
    owner = repo.acquire()
    with pytest.raises(MarketDataError):
        repo.acquire()
    repo.release("wrong-owner")
    with pytest.raises(MarketDataError):
        repo.acquire()
    repo.release(owner)
    repo.release(repo.acquire())


def test_transport_retries_are_bounded_persisted_and_secret_safe(environment):
    settings, store, clock, repo = environment
    client = Mock()
    client.history.side_effect = TimeoutError("secret-key=never-log")
    provider = YahooDailyProvider(settings, Mock(return_value=client), clock)
    result = MarketIngestion(repo, provider, clock, clock.sleep).run(
        ["AAPL"], date(2026, 10, 15), date(2026, 10, 19)
    )
    assert result["status"] == "failed"
    assert result["results"][0]["attempts"] == 3
    assert client.history.call_count == 3
    assert len([r for r in store.all("market_runs") if r["kind"] == "attempt_start"]) == 3
    assert "secret-key" not in json.dumps(store.all("market_runs"))
    assert store.get("news_locks", "market:yfinance") is None


def test_rate_limit_cooldown_and_daily_budget_survive_new_instance(environment):
    settings, store, clock, repo = environment
    client = Mock()
    client.history.side_effect = YFRateLimitError()
    provider = YahooDailyProvider(settings, Mock(return_value=client), clock)
    runner = MarketIngestion(repo, provider, clock, clock.sleep)
    args = (["AAPL", "MSFT"], date(2026, 10, 15), date(2026, 10, 19))
    result = runner.run(*args)
    assert result["status"] == "failed"
    assert client.history.call_count == 1
    assert result["results"][1]["error"] == "cooldown"
    clock.sleep(301)
    settings.market_daily_budget = 1
    again = MarketIngestion(
        MarketRepository(Store(settings), clock), provider, clock, clock.sleep
    ).run(*args)
    assert again["results"][0]["error"] == "budget"
    assert client.history.call_count == 1


def test_partial_ticker_failure_not_success(environment):
    settings, _, clock, repo = environment
    provider = YahooDailyProvider(settings, clock=clock)
    provider.fetch = Mock(side_effect=[receipt(clock), MarketDataError("provider", "safe")])
    result = MarketIngestion(repo, provider, clock, clock.sleep).run(
        ["AAPL", "MSFT"], date(2026, 10, 15), date(2026, 10, 19)
    )
    assert result["status"] == "partial"
    assert result["results"][0]["status"] == "success"
    assert result["results"][1]["status"] == "failed"


def test_cli_status_migration_and_blocked_ingestion(tmp_path, monkeypatch, capsys):
    settings = Settings(_env_file=None, runtime_dir=tmp_path)
    monkeypatch.setattr("src.platform.market_data.Settings", lambda: settings)
    assert main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["access"] == "blocked"
    assert main(["migrate"]) == 0
    capsys.readouterr()
    assert (
        main(["ingest", "--start", "2026-10-15", "--end", "2026-10-19", "--tickers", "AAPL"]) == 1
    )
    assert json.loads(capsys.readouterr().out)["code"] == "access_blocked"


def test_frozen_reference_hashes_unchanged():
    import hashlib

    # The source fingerprint and weights are checked by the existing artifact regression suite.
    protocol = Path("reports/research/m4_2_prospective_protocol_v1.json")
    assert (
        hashlib.sha256(protocol.read_bytes()).hexdigest()
        == "9d9aaf888b02e09206c9d7a83c10e9b53da351296ffd8c40d3ee2c400e32a272"
    )
    sources = {
        "src/platform/forecast_contract.py": "4b46f070f67ce56bc5e9ec7ad9f2dcc2e94d682704f0c1082a667a87c06e5eca",
        "src/platform/model_artifacts.py": "2940ee63a9da4cb2c54fa4af241f09118853844505ac2ec1a9c5cd9bdb740355",
        "src/platform/model_training.py": "0b445e698844cbd2581aad771c03b184a066ec1146d51284b1993923a62853a8",
        "src/platform/research.py": "fe0bc5ea0f94e8da6da23b0a265224a8846a98863746d6d7621c50f0d6b0939e",
        "src/feature_engineering.py": "28f39697b26e5850d44322bf6e842b668830b7df63c019c4c44fc7323937cd2e",
        "src/model_baseline.py": "ad678c3c5bdd7ff696b91688717ce8501f257291380f079d9b011beb495e3e0c",
    }
    # Git checkouts may use CRLF on Windows; code content must stay identical on both OSes.
    assert all(
        hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == digest
        for path, digest in sources.items()
    )


def test_unpublished_observation_is_never_used_and_retry_cannot_backdate(environment, monkeypatch):
    _, store, clock, repo = environment
    observation = receipt(clock)
    original = store.add

    def crash(name, payload, identity=None, connection=None):
        if name == "market_runs" and str(identity).startswith("commit:"):
            raise RuntimeError("simulated crash after data commit")
        return original(name, payload, identity, connection)

    monkeypatch.setattr(store, "add", crash)
    with pytest.raises(RuntimeError):
        persist(repo, clock, observation)
    assert store.get("market_observations", str(observation.receipt_id)) is not None
    with pytest.raises(MarketDataError):
        repo.history("AAPL", clock())
    unavailable_cutoff = clock()
    clock.sleep(30)
    monkeypatch.setattr(store, "add", original)
    assert repo.persist(observation)["new_observation"] is False
    assert repo.history("AAPL", clock())[1]["available_at"] == stamp(clock())
    with pytest.raises(MarketDataError):
        repo.history("AAPL", unavailable_cutoff)


def test_late_committed_older_receipt_does_not_replace_newer_vintage(environment):
    _, _, clock, repo = environment
    older = receipt(clock)
    clock.sleep(10)
    newer = receipt(clock, frame(close=102))
    persist(repo, clock, newer)
    before_late_commit = clock()
    clock.sleep(10)
    repo.persist(older)
    assert repo.history("AAPL", clock())[0].close_price.tolist() == [102] * 3
    assert len(repo.revisions("AAPL", before_late_commit)) == 3
    assert len(repo.revisions("AAPL", clock())) == 6


def test_no_vintage_stitching_and_fixture_provenance_not_mixed(environment):
    _, _, clock, repo = environment
    persist(repo, clock, receipt(clock))
    clock.sleep(10)
    short = receipt(
        clock, frame(("2026-10-19",)), requested_start="2026-10-19", source_kind="provider"
    )
    assert persist(repo, clock, short)["new_revisions"] == 1
    assert len(repo.history("AAPL", clock())[0]) == 1
    versions = repo.revisions("AAPL", clock())
    assert {r["source_kind"] for r in versions} == {"fixture", "provider"}


@pytest.mark.parametrize("ticker", ["AAPL", "SAP.DE"])
def test_winter_exchange_midnight_preserves_trading_date(environment, ticker):
    clock = Clock("2026-01-05T22:00:00+00:00")
    sample = receipt(
        clock,
        frame(("2026-01-05",), ticker),
        ticker=ticker,
        requested_start="2026-01-05",
        requested_end="2026-01-05",
    )
    data, quality = inspect_receipt(sample)
    assert quality["status"] == "accepted"
    assert str(data.trade_date.iloc[0]) == "2026-01-05"


def test_revision_times_do_not_use_lexical_fractional_second_order(environment):
    _, _, clock, repo = environment
    first = receipt(clock)
    clock.sleep(0.1)
    second = receipt(clock)
    persist(repo, clock, second)
    repo.persist(first)
    assert all(
        pd.Timestamp(r["first_seen_at"]) == pd.Timestamp(first.received_at)
        for r in repo.revisions("AAPL", clock())
    )


def test_postgres_market_table_ddl_compiles_without_database():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable

    from src.platform.market_data_store import market_metadata

    for table in market_metadata.tables.values():
        sql = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert "JSON" in sql and "PRIMARY KEY" in sql


@pytest.mark.skipif(
    __import__("os").getenv("SI_TEST_POSTGRES") != "1",
    reason="Keine ausdrückliche isolierte PostgreSQL-Testdatenbank",
)
def test_postgres_additive_market_persistence():
    from uuid import uuid4

    from src.database import get_engine

    # Uses only explicitly opted-in test DB, never an implicit production connection.
    engine = get_engine()
    store = Store(Settings(_env_file=None, mode="live"), engine=engine)
    store.migrate()
    clock = Clock()
    repo = MarketRepository(store, clock)
    repo.migrate()
    observation = receipt(clock, receipt_id=uuid4())
    persist(repo, clock, observation)
    assert repo.persist(observation)["new_observation"] is False
    assert (
        store.get("market_observations", str(observation.receipt_id))["payload_sha256"]
        == observation.payload_sha256
    )
    engine.dispose()
