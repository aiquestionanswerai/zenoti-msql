import os
import re
import logging
from datetime import datetime
import pyodbc
from dotenv import load_dotenv
from gdrive_helper import list_csv_filenames

dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path)

SERVER = os.getenv("SERVER")
DATABASE = os.getenv("DATABASE")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

if not all([SERVER, DATABASE, DB_USER, DB_PASSWORD]):
    missing = [k for k, v in {"SERVER": SERVER, "DATABASE": DATABASE, "DB_USER": DB_USER, "DB_PASSWORD": DB_PASSWORD}.items() if not v]
    raise ValueError(f"Missing environment variables: {', '.join(missing)}")

conn_str = (
    f"DRIVER={{ODBC Driver 18 for SQL Server}};"
    f"SERVER={SERVER};"
    f"DATABASE={DATABASE};"
    f"UID={DB_USER};"
    f"PWD={DB_PASSWORD};"
)

CSV_SOURCE = os.getenv("CSV_SOURCE", "local").lower()

log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"sql_helper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(),
    ],
)

TABLE_CONFIG = [
    {
        "table_env": "TABLE_APPOINTMENTS",
        "date_column": "appointment_date",
        "csv_prefix": "appointments",
        "folder_env": "GDRIVE_FOLDER_APPOINTMENTS",
        "date_format": "%Y-%m-%d",
    },
    {
        "table_env": "TABLE_CASH",
        "date_column": "payment_date",
        "csv_prefix": "sales-cash",
        "folder_env": "GDRIVE_FOLDER_CASH",
        "date_format": "%Y/%m/%d",
    },
    {
        "table_env": "TABLE_COG",
        "date_column": "transaction_date",
        "csv_prefix": "cost_of_goods",
        "folder_env": "GDRIVE_FOLDER_COG",
        "date_format": "%Y/%m/%d",
    },
    {
        "table_env": "TABLE_BLOCK_OUT",
        "date_column": "date",
        "csv_prefix": "attendance",
        "folder_env": "GDRIVE_FOLDER_BLOCK_OUT",
        "date_format": "%m/%d/%Y",
    },
]

DATE_RANGE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})")


def extract_date_range(filenames, prefix):
    """Find the file matching prefix and extract start/end dates from filename."""
    for name in filenames:
        if name.lower().startswith(prefix.lower()):
            match = DATE_RANGE_PATTERN.search(name)
            if match:
                return match.group(1), match.group(2)
    return None, None


def delete_data_for_range(cursor, table, date_column, start_date, end_date):
    """Delete rows where date_column is between start_date and end_date."""
    sql = f"DELETE FROM dbo.[{table}] WHERE [{date_column}] >= ? AND [{date_column}] <= ?"
    cursor.execute(sql, [start_date, end_date])
    return cursor.rowcount


def main():
    logging.info("sql_helper started")
    logging.info(f"CSV source: {CSV_SOURCE}")
    logging.info(f"Database: {SERVER}/{DATABASE}")

    credentials_json = os.getenv("GDRIVE_CREDENTIALS_JSON")
    credentials_file = os.getenv("GDRIVE_CREDENTIALS_FILE", "service_account.json")

    conn = pyodbc.connect(conn_str)
    logging.info("Connected to database")
    cursor = conn.cursor()

    total_deleted = 0

    for config in TABLE_CONFIG:
        table = os.getenv(config["table_env"])
        if not table:
            logging.warning(f"SKIP: {config['table_env']} not set in env")
            continue

        logging.info(f"Processing {config['table_env']} → {table}")

        folder_id = os.getenv(config["folder_env"])

        if CSV_SOURCE == "gdrive" and folder_id:
            logging.info(f"Listing files from GDrive folder: {folder_id}")
            filenames = list_csv_filenames(
                folder_id,
                credentials_json=credentials_json,
                credentials_file=credentials_file,
            )
            logging.info(f"Found {len(filenames)} file(s): {filenames}")
        else:
            csv_path = os.getenv(f"CSV_FILE_{config['table_env'].replace('TABLE_', '')}")
            if csv_path and os.path.isdir(csv_path):
                filenames = os.listdir(csv_path)
            elif csv_path:
                filenames = [os.path.basename(csv_path)]
            else:
                logging.warning(f"SKIP: No CSV source found for {config['table_env']}")
                continue
            logging.info(f"Local files: {filenames}")

        start_date, end_date = extract_date_range(filenames, config["csv_prefix"])

        if not start_date or not end_date:
            logging.warning(f"SKIP: No date range found in filenames for prefix '{config['csv_prefix']}'. Files: {filenames}")
            continue

        logging.info(f"Extracted date range from filename: {start_date} to {end_date}")

        date_fmt = config["date_format"]
        start_date = datetime.strptime(start_date, "%Y-%m-%d").strftime(date_fmt)
        end_date = datetime.strptime(end_date, "%Y-%m-%d").strftime(date_fmt)

        logging.info(f"Deleting from {table} where [{config['date_column']}] between {start_date} and {end_date}...")

        try:
            deleted = delete_data_for_range(cursor, table, config["date_column"], start_date, end_date)
            logging.info(f"Deleted {deleted:,} rows from {table}.")
            total_deleted += deleted
        except pyodbc.Error as e:
            logging.error(f"DELETE failed for {table}: {e}")
            conn.rollback()
            raise

    conn.commit()
    logging.info("Transaction committed.")
    cursor.close()
    conn.close()

    logging.info(f"sql_helper complete. Total rows deleted across all tables: {total_deleted:,}")


if __name__ == "__main__":
    main()
