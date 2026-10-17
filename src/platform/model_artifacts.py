"""Trusted local M4 final artifacts. Hashes detect corruption, not an untrusted owner."""

import hashlib
import json
import platform
import re
import tempfile
from contextlib import contextmanager
from datetime import date, timezone
from pathlib import Path
from typing import Literal

import exchange_calendars
import joblib
import numpy as np
import pandas as pd
import scipy
import sklearn
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from .forecast_contract import (
    CONTRACT_VERSION,
    FEATURE_SCHEMA,
    FEATURE_VERSION,
    INPUT_COLUMNS,
    FeatureSnapshot,
    ForecastError,
    ResearchPrediction,
    SourceProvenance,
    utc,
    utc_now,
)
from .research import logit

ARTIFACT_FORMAT = "m4-final-calibrated-v1"
ID_PATTERN = r"^m4-(?:logistic|random_forest)-[a-f0-9]{24}$"


def canonical_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def runtime_versions():
    return {
        "python": platform.python_version(),
        "sklearn": sklearn.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "joblib": joblib.__version__,
        "exchange_calendars": exchange_calendars.__version__,
    }


def code_version():
    from src import feature_engineering, model_baseline

    from . import forecast_contract, model_training, research

    modules = [feature_engineering, model_baseline, forecast_contract, model_training, research]
    return canonical_hash(
        {Path(module.__file__).name: file_hash(module.__file__) for module in modules}
        | {"model_artifacts.py": file_hash(__file__)}
    )


class ArtifactMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    artifact_format: Literal["m4-final-calibrated-v1"] = ARTIFACT_FORMAT
    artifact_id: str = Field(pattern=ID_PATTERN)
    model_id: Literal["logistic", "random_forest"]
    model_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    artifact_kind: Literal["final_research"] = "final_research"
    status: Literal["research_only"] = "research_only"
    forecast_enabled: Literal[False] = False
    created_at: AwareDatetime
    knowledge_available_at: AwareDatetime
    contract_version: Literal["next-session-close-direction-v1"] = CONTRACT_VERSION
    feature_version: Literal["pipeline-six-v1"] = FEATURE_VERSION
    feature_schema: dict[str, str]
    input_columns: list[str]
    code_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    library_versions: dict[str, str]
    source: SourceProvenance
    input_data_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    training_data_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    calibration_data_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    training_spec: dict
    training_period: dict
    calibration_period: dict
    instruments: dict[str, dict]
    hyperparameters: dict
    calibration_hyperparameters: dict
    training_positive_rate: float = Field(ge=0, le=1)
    evaluation_plan: dict
    limitations: list[str]

    @field_validator("created_at", "knowledge_available_at")
    @classmethod
    def times_utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def chronology(self):
        from .model_training import TrainingSpec

        spec = TrainingSpec.model_validate(self.training_spec)
        train = self.training_period
        calibration = self.calibration_period
        if (
            spec.model != self.model_id
            or set(spec.tickers) != set(self.instruments)
            or date.fromisoformat(train["last_label_session"]) > spec.train_end
            or date.fromisoformat(train["last_label_session"])
            >= date.fromisoformat(calibration["start"])
            or date.fromisoformat(calibration["last_label_session"]) > spec.calibration_end
            or utc(self.knowledge_available_at) > utc(self.created_at)
        ):
            raise ValueError("Inkonsistente Modell-/Trainings-/Zeitmetadaten")
        return self


def read_json(path, max_bytes=2 * 1024 * 1024):
    path = Path(path)
    if path.stat().st_size > max_bytes:
        raise ForecastError("metadata_size", "Artefaktmetadaten sind zu groß")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise ForecastError("invalid_metadata", "Ungültige Artefaktmetadaten") from None


class ArtifactRepository:
    def __init__(self, root):
        # The caller explicitly selects a local directory. No URLs or upload deserialization.
        self.root = Path(root).resolve()

    def path(self, identity):
        if not re.fullmatch(ID_PATTERN, identity):
            raise ForecastError(
                "artifact_id", "Ungültige Modellartefakt-ID; kein Dateipfad erlaubt"
            )
        folder = self.root / identity
        if folder.is_symlink() or not folder.resolve().is_relative_to(self.root):
            raise ForecastError(
                "artifact_path", "Artefakt liegt außerhalb des vertrauenswürdigen Verzeichnisses"
            )
        return folder

    def _file(self, folder, name):
        path = folder / name
        if path.is_symlink() or not path.resolve().is_relative_to(self.root) or not path.is_file():
            raise ForecastError(
                "artifact_file", "Lokale Artefaktdatei fehlt oder ist ein unzulässiger Link"
            )
        return path

    def _registry(self):
        path = self.root / "registry.json"
        if not path.exists():
            return {"schema_version": 1, "artifacts": {}}
        self._file(self.root, "registry.json")
        result = read_json(path)
        if result.get("schema_version") != 1 or not isinstance(result.get("artifacts"), dict):
            raise ForecastError("registry_schema", "Unbekanntes lokales Registry-Format")
        return result

    @contextmanager
    def writing(self):
        self.root.mkdir(parents=True, exist_ok=True)
        lock = self.root / ".writer-lock"
        try:
            lock.mkdir()
        except FileExistsError:
            raise ForecastError(
                "artifact_busy", "Ein Artefakt-Schreibvorgang läuft; lokale Registry prüfen"
            ) from None
        try:
            yield
        finally:
            lock.rmdir()  # Only our newly created empty lock, never a model/data directory.

    def save(self, metadata, bundle):
        folder = self.path(metadata.artifact_id)
        with self.writing():
            registry = self._registry()
            if folder.exists() or metadata.artifact_id in registry["artifacts"]:
                existing = self.metadata(metadata.artifact_id)
                if existing.model_version != metadata.model_version:
                    raise ForecastError(
                        "artifact_collision", "Bestehendes Artefakt wird nicht überschrieben"
                    )
                return existing
            temporary = Path(tempfile.mkdtemp(prefix=".building-", dir=self.root))
            model_path = temporary / "model.joblib"
            joblib.dump(bundle, model_path, compress=3)
            (temporary / "metadata.json").write_text(
                metadata.model_dump_json(indent=2), encoding="utf-8"
            )
            entry = {
                "model_sha256": file_hash(model_path),
                "metadata_sha256": file_hash(temporary / "metadata.json"),
                "model_version": metadata.model_version,
            }
            temporary.rename(folder)
            registry["artifacts"][metadata.artifact_id] = entry
            # Serialize writers and atomically replace only the registry index.
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.root, delete=False, prefix=".registry-"
            ) as stream:
                json.dump(registry, stream, indent=2, sort_keys=True)
                index_path = Path(stream.name)
            index_path.replace(self.root / "registry.json")
        return metadata

    def metadata(self, identity, *, expected_version=None):
        folder = self.path(identity)
        entry = self._registry()["artifacts"].get(identity)
        if not entry:
            raise ForecastError(
                "unregistered_artifact",
                "Kein registriertes finales Modell; Fold-Artefakte sind unzulässig",
            )
        metadata_path = self._file(folder, "metadata.json")
        model_path = self._file(folder, "model.joblib")
        if model_path.stat().st_size > 256 * 1024 * 1024:
            raise ForecastError(
                "artifact_size", "Modellartefakt überschreitet das lokale Größenlimit"
            )
        if file_hash(metadata_path) != entry.get("metadata_sha256") or file_hash(
            model_path
        ) != entry.get("model_sha256"):
            raise ForecastError("integrity", "SHA256-Integrität des Modellartefakts verletzt")
        try:
            result = ArtifactMetadata.model_validate(read_json(metadata_path))
        except (ValueError, KeyError, TypeError):
            raise ForecastError(
                "metadata_schema", "Inkompatibler oder nicht erlaubter Modellmetadatenvertrag"
            ) from None
        if (
            result.artifact_id != identity
            or result.model_version != entry["model_version"]
            or identity != f"m4-{result.model_id}-{result.model_version[:24]}"
        ):
            raise ForecastError(
                "artifact_identity", "Modell-ID und Modellversion stimmen nicht überein"
            )
        if expected_version is not None and result.model_version != expected_version:
            raise ForecastError("model_version", "Angeforderte Modellversion stimmt nicht überein")
        if result.feature_schema != FEATURE_SCHEMA or result.input_columns != INPUT_COLUMNS:
            raise ForecastError("feature_schema", "Modell passt nicht zum aktuellen Feature-Schema")
        if result.library_versions != runtime_versions() or result.code_version != code_version():
            raise ForecastError(
                "runtime_version",
                "Python-/Library-/Codeversion inkompatibel; explizit neu trainieren",
            )
        return result

    def load(self, identity, *, trusted=False, expected_version=None):
        if not trusted:
            raise ForecastError(
                "untrusted_artifact",
                "Joblib nur aus selbst kontrollierter lokaler Registry laden; trusted=True erforderlich",
            )
        metadata = self.metadata(identity, expected_version=expected_version)
        model_path = self._file(self.path(identity), "model.joblib")
        # Same open descriptor is checked and deserialized, reducing file-swap races.
        with model_path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != self._registry()["artifacts"][identity]["model_sha256"]:
                raise ForecastError("integrity", "Modell wurde während des Ladens verändert")
            stream.seek(0)
            bundle = joblib.load(stream)
        expected_keys = {
            "artifact_format",
            "artifact_id",
            "model_version",
            "model",
            "calibrator",
            "input_columns",
        }
        if (
            not isinstance(bundle, dict)
            or set(bundle) != expected_keys
            or bundle["artifact_format"] != ARTIFACT_FORMAT
            or bundle["artifact_id"] != identity
            or bundle["model_version"] != metadata.model_version
            or bundle["input_columns"] != INPUT_COLUMNS
        ):
            raise ForecastError(
                "artifact_kind", "Kein zulässiges finales Inferenzartefakt; Fold-Modell abgelehnt"
            )
        if (
            not isinstance(bundle["model"], Pipeline)
            or not isinstance(bundle["calibrator"], LogisticRegression)
            or list(bundle["model"].feature_names_in_) != INPUT_COLUMNS
        ):
            raise ForecastError(
                "estimator_schema", "Gespeicherte Pipeline/Feature-Eingaben sind inkompatibel"
            )
        classifier = bundle["model"].named_steps.get("classifier")
        expected_type = (
            LogisticRegression if metadata.model_id == "logistic" else RandomForestClassifier
        )
        if (
            set(bundle["model"].named_steps) != {"preprocessing", "classifier"}
            or not isinstance(classifier, expected_type)
            or classifier.get_params() != metadata.hyperparameters
            or bundle["calibrator"].get_params() != metadata.calibration_hyperparameters
            or list(classifier.classes_) != [0, 1]
            or list(bundle["calibrator"].classes_) != [0, 1]
        ):
            raise ForecastError(
                "estimator_schema",
                "Estimator, Zielklassen oder Hyperparameter passen nicht zu den Metadaten",
            )
        return LoadedResearchModel(metadata, bundle, actual)


class LoadedResearchModel:
    def __init__(self, metadata, bundle, checksum):
        self.metadata, self.bundle, self.checksum = metadata, bundle, checksum

    def _probabilities(self, frame):
        if list(frame.columns) != INPUT_COLUMNS or frame.empty:
            raise ForecastError(
                "feature_schema", "Inferenz-Eingaben stimmen nicht mit dem Modell überein"
            )
        if not set(frame.ticker).issubset(self.metadata.instruments):
            raise ForecastError(
                "unknown_instrument", "Aktie gehört nicht zum trainierten Universum"
            )
        if not np.isfinite(frame[INPUT_COLUMNS[:-1]].to_numpy(dtype=float)).all():
            raise ForecastError("incomplete_features", "Inferenz-Features sind unvollständig")
        raw = self.bundle["model"].predict_proba(frame)[:, 1]
        return self.bundle["calibrator"].predict_proba(logit(raw))[:, 1]

    def predict_research(self, snapshot: FeatureSnapshot, *, clock=utc_now):
        snapshot = FeatureSnapshot.model_validate(snapshot.model_dump())
        metadata = self.metadata
        generated = utc(clock())
        if utc(snapshot.prepared_at) > generated or utc(snapshot.decision_at) < utc(
            metadata.knowledge_available_at
        ):
            raise ForecastError(
                "model_not_available",
                "Modell-/Trainingsdaten waren zum Entscheidungszeitpunkt noch nicht verfügbar",
            )
        if snapshot.mode == "current" and (
            generated - utc(snapshot.decision_at) > pd.Timedelta(minutes=5)
            or utc(metadata.created_at) > utc(snapshot.decision_at)
        ):
            raise ForecastError(
                "stale_request", "Modell/aktuelle Inferenzanforderung ist zeitlich nicht zulässig"
            )
        instrument = metadata.instruments.get(snapshot.ticker)
        if not instrument or (snapshot.calendar, snapshot.exchange) != (
            instrument["calendar"],
            instrument["exchange"],
        ):
            raise ForecastError(
                "instrument_mapping", "Instrument-/Börsen-/Kalenderzuordnung passt nicht zum Modell"
            )
        if snapshot.feature_as_of <= date.fromisoformat(metadata.training_spec["calibration_end"]):
            raise ForecastError(
                "training_overlap",
                "Inferenz liegt innerhalb des Modell-Trainings-/Kalibrierungszeitraums",
            )
        frame = pd.DataFrame(
            [{**snapshot.features, "ticker": snapshot.ticker}], columns=INPUT_COLUMNS
        )
        probability = float(self._probabilities(frame)[0])
        return ResearchPrediction(
            **snapshot.model_dump(),
            model_id=metadata.artifact_id,
            model_version=metadata.model_version,
            artifact_sha256=self.checksum,
            model_created_at=metadata.created_at,
            model_knowledge_available_at=metadata.knowledge_available_at,
            generated_at=generated.to_pydatetime(),
            probability=probability,
            counterfactual_model_replay=utc(metadata.created_at) > utc(snapshot.decision_at),
        )
