from pathlib import Path
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL


# Hauptordner des Git-Repositories ermitteln
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Lokale Zugangsdaten laden
load_dotenv(PROJECT_ROOT / ".env")


def get_engine() -> Engine:
    """
    Erstellt eine SQLAlchemy-Verbindung zur PostgreSQL-Datenbank.
    """

    required_variables = [
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
    ]

    missing_variables = [
        variable
        for variable in required_variables
        if not os.getenv(variable)
    ]

    if missing_variables:
        raise RuntimeError(
            "Folgende Umgebungsvariablen fehlen in der .env-Datei: "
            + ", ".join(missing_variables)
        )

    database_url = URL.create(
        drivername="postgresql+psycopg2",
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME"),
    )

    return create_engine(
        database_url,
        pool_pre_ping=True,
    )


def test_connection() -> None:
    """
    Prüft, ob die Verbindung zur Datenbank funktioniert.
    """

    engine = get_engine()

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    print("Database connection successful.")


if __name__ == "__main__":
    test_connection()