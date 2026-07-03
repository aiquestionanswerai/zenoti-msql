import os
import pandas as pd
import numpy as np
import pyodbc
import uuid
import logging
from dotenv import load_dotenv
from decimal import Decimal, InvalidOperation
from datetime import datetime

# Load environment variables from .env file
dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path)

# ==================================
# Read Config from .env file
# ==================================
SERVER = os.getenv("SERVER")
DATABASE = os.getenv("DATABASE")
TABLE = os.getenv("TABLE_BLOCK_OUT") # Assuming the table name is in .env
CSV_FILE = os.getenv("CSV_FILE_BLOCK_OUT") # Assuming the CSV file path is in .env
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

CSV_SOURCE = os.getenv("CSV_SOURCE", "local").lower()
if CSV_SOURCE == "gdrive":
    from gdrive_helper import get_csv_from_gdrive
    CSV_FILE = get_csv_from_gdrive(
        os.getenv("GDRIVE_FOLDER_BLOCK_OUT"),
        credentials_json=os.getenv("GDRIVE_CREDENTIALS_JSON"),
        credentials_file=os.getenv("GDRIVE_CREDENTIALS_FILE", "service_account.json"),
    )

if not all([SERVER, DATABASE, TABLE, CSV_FILE, DB_USER, DB_PASSWORD]):
    missing = [
        k
        for k, v in {
            "SERVER": SERVER,
            "DATABASE": DATABASE,
            "TABLE_BLOCK_OUT": TABLE,
            "CSV_FILE_BLOCK_OUT": CSV_FILE,
            "DB_USER": DB_USER,
            "DB_PASSWORD": DB_PASSWORD,
        }.items()
        if not v
    ]
    raise ValueError(f"Missing environment variables in .env file: {', '.join(missing)}")

# ==================================
# Build Connection String
# ==================================
conn_str = (
    f"DRIVER={{ODBC Driver 18 for SQL Server}};"
    f"SERVER={SERVER};"
    f"DATABASE={DATABASE};"
    f"UID={DB_USER};"
    f"PWD={DB_PASSWORD};"
)

# ==================================
# Setup Logging
# ==================================
log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(log_dir, exist_ok=True)
log_file_name = f"block_out_update_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
log_file_path = os.path.join(log_dir, log_file_name)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler() # To also print to console
    ]
)

# ==================================
# Load and Process CSV
# ==================================
try:
    df = pd.read_csv(CSV_FILE, dtype=str, keep_default_na=False)
    logging.info(f"Processing CSV: {CSV_FILE}")
    logging.info(f"Found {len(df):,} rows in {os.path.basename(CSV_FILE)}")
except FileNotFoundError:
    raise FileNotFoundError(f"The specified CSV file was not found: {CSV_FILE}")

# --- Data Transformations ---

# 1. Split 'Schedule' into 'start_time' and 'end_time'
schedule_split = df["Schedule"].str.split(" - ", n=1, expand=True)
df["start_time"] = schedule_split[0]
df["end_time"] = schedule_split[1]

# 2. Convert times to 24-hour format (HH:MM:SS)
df["start_time"] = pd.to_datetime(df["start_time"], format="%I:%M %p").dt.strftime("%H:%M:%S")
df["end_time"] = pd.to_datetime(df["end_time"], format="%I:%M %p").dt.strftime("%H:%M:%S")

# 3. Convert 'Schedule Status' — "Working" → 0, all others → 1
STATUS_MAP = {"Working": 0}

def convert_status(status_str):
    return STATUS_MAP.get(status_str, 1)

df["status"] = df["Schedule Status"].apply(convert_status)

# 4. Convert Date format
df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%m/%d/%Y')

# 5. Convert hour columns from HH:MM string to float
def convert_hours_to_float(time_str):
    """Converts a time string 'HH:MM' to a float."""
    try:
        if isinstance(time_str, str) and ':' in time_str:
            hours, minutes = map(int, time_str.split(':'))
            return hours + (minutes / 60.0)
        # If it's already a number or can be converted, use it directly
        return float(time_str)
    except (ValueError, TypeError):
        # Return 0.0 or another default if conversion fails
        return 0.0

def convert_minutes_to_hours_decimal(minutes_str):
    """Converts a string of minutes to a Decimal of hours with 2 decimal places."""
    try:
        minutes = Decimal(minutes_str)
        return (minutes / Decimal('60.0')).quantize(Decimal('0.01'))
    except (ValueError, TypeError, InvalidOperation):
        return Decimal('0.00')

df['Scheduled Hours'] = df['Scheduled Hours'].apply(convert_hours_to_float)
df['Booked Hours'] = df['Booked Hours'].apply(convert_hours_to_float)
df['Block Out Hours Paid'] = df['Block Out Hours Paid'].apply(convert_minutes_to_hours_decimal)

def format_float_to_hhmm(hour_float):
    """Converts a float representing hours to an 'HH:MM' string format."""
    total_minutes = round(hour_float * 60)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"



# ==================================
# Update Database
# ==================================

updated_rows = 0
inserted_rows = 0
failed_rows = 0

try:
    with pyodbc.connect(conn_str) as conn:
        cursor = conn.cursor()
        logging.info("Successfully connected to the database.")

        # Iterate over each row in the DataFrame to perform updates
        for index, row in df.iterrows():
            # Define the values for the WHERE clause from the CSV row
            where_conditions = {
                "date": row["Date"],
                "employee_name": row["Employee Name"],
                "center_name": row["Work Center"],
            }

            # Values to update
            update_value = row["Block Out Hours Paid"]
            csv_job_name = row["Job"]
            scheduled_hours_value = format_float_to_hhmm(row["Scheduled Hours"])
            booked_hours_value = format_float_to_hhmm(row["Booked Hours"])

            # Construct key-match WHERE clause (date, employee, center)
            key_where_parts = []
            key_params = []
            for col, val in where_conditions.items():
                if pd.isna(val) or val == '':
                    key_where_parts.append(f"[{col}] IS NULL")
                else:
                    key_where_parts.append(f"[{col}] = ?")
                    key_params.append(val)

            key_where_clause = " AND ".join(key_where_parts)

            try:
                # Check if a row exists by key columns
                check_sql = f"SELECT TOP 1 [block_out_hours_paid], [job_name], [scheduled_hours], [booked_hours] FROM {TABLE} WHERE {key_where_clause}"

                cursor.execute(check_sql, key_params)
                existing_row = cursor.fetchone()

                if existing_row is not None:
                    current_paid, current_job, current_scheduled_hours, current_booked_hours = existing_row
                    set_parts = []
                    set_params = []

                    if (pd.isna(current_paid) or current_paid in [None, ""]) and not (pd.isna(update_value) or update_value in [None, ""]):
                        set_parts.append("[block_out_hours_paid] = ?")
                        set_params.append(update_value)

                    if (pd.isna(current_job) or (isinstance(current_job, str) and current_job.strip() == "")) and not (pd.isna(csv_job_name) or (isinstance(csv_job_name, str) and csv_job_name.strip() == "")):
                        set_parts.append("[job_name] = ?")
                        set_params.append(csv_job_name)

                    if not (pd.isna(scheduled_hours_value) or (isinstance(scheduled_hours_value, str) and scheduled_hours_value.strip() == "")):
                        set_parts.append("[scheduled_hours] = ?")
                        set_params.append(scheduled_hours_value)

                    if not (pd.isna(booked_hours_value) or (isinstance(booked_hours_value, str) and booked_hours_value.strip() == "")):
                        set_parts.append("[booked_hours] = ?")
                        set_params.append(booked_hours_value)

                    if set_parts:
                        update_sql = f"UPDATE {TABLE} SET {', '.join(set_parts)} WHERE {key_where_clause}"
                        update_params = set_params + key_params

                        cursor.execute(update_sql, update_params)
                        if cursor.rowcount > 0:
                            updated_rows += cursor.rowcount
                            logging.info(f"SUCCESS: Updated row {index} for '{row['Employee Name']}' on {row['Date']}. Applied changes: {', '.join(set_parts)}.")
                        else:
                            logging.info(f"SKIPPED: Row {index} for '{row['Employee Name']}' on {row['Date']} already had the needed values.")
                    else:
                        logging.info(f"SKIPPED: Row {index} for '{row['Employee Name']}' on {row['Date']} already had the needed values.")
                else:
                    # If no match is found, perform an INSERT
                    logging.info(f"--- No match found for CSV row {index}. Attempting to insert. ---")
                    
                    try:
                        insert_columns = [
                            "schedule_id", "date", "employee_name", "job_name", "status", "center_name",
                            "start_time", "end_time", "scheduled_hours", "booked_hours",
                            "block_out_hours_paid"
                        ]
                        
                        insert_values = [
                            f"{str(uuid.uuid4())}esg",
                            row["Date"],
                            row["Employee Name"],
                            row["Job"],
                            row["status"],
                            row["Work Center"],
                            row["start_time"],
                            row["end_time"],
                            format_float_to_hhmm(row["Scheduled Hours"]),
                            format_float_to_hhmm(row["Booked Hours"]),
                            row["Block Out Hours Paid"]
                        ]

                        placeholders = ", ".join(["?"] * len(insert_columns))
                        insert_sql = f"INSERT INTO {TABLE} ([{'], ['.join(insert_columns)}]) VALUES ({placeholders})"
                        
                        cursor.execute(insert_sql, insert_values)
                        inserted_rows += cursor.rowcount
                        logging.info(f"SUCCESS: Inserted new record for '{row['Employee Name']}' on {row['Date']}.")
                    
                    except pyodbc.Error as insert_ex:
                        failed_rows += 1
                        logging.error(f"Error inserting row {index}: {insert_ex}")
                        logging.error(f"Problematic Row Data for Insert: \n{row}")
                    
                    logging.info("-" * 50)
            except pyodbc.Error as ex:
                failed_rows += 1
                sqlstate = ex.args[0]
                logging.error(f"Database error occurred for row {index}: {sqlstate}")
                logging.error(f"Problematic Row Data: \n{row}")
                logging.error(f"SQL: {update_sql}")
                logging.error(f"Params: {update_params}")

        # ==================================
        # Delete orphan DB records not in CSV (within CSV date range)
        # ==================================
        deleted_rows = 0

        min_date = pd.to_datetime(df['Date'], format='%m/%d/%Y').min().strftime('%m/%d/%Y')
        max_date = pd.to_datetime(df['Date'], format='%m/%d/%Y').max().strftime('%m/%d/%Y')
        logging.info(f"\nOrphan cleanup: scanning DB for records in date range {min_date} — {max_date} not found in CSV.")

        csv_keys = set(
            (row["Date"], row["Employee Name"], row["Work Center"])
            for _, row in df.iterrows()
        )

        fetch_sql = f"SELECT [date], [employee_name], [center_name], [schedule_id] FROM {TABLE} WHERE [date] >= ? AND [date] <= ?"
        cursor.execute(fetch_sql, [min_date, max_date])
        db_rows = cursor.fetchall()
        logging.info(f"Found {len(db_rows)} DB record(s) in date range.")

        for db_row in db_rows:
            db_date_raw, db_employee, db_center, db_schedule_id = db_row

            if isinstance(db_date_raw, datetime):
                db_date = db_date_raw.strftime('%m/%d/%Y')
            else:
                db_date = pd.to_datetime(str(db_date_raw)).strftime('%m/%d/%Y')

            db_key = (db_date, db_employee, db_center)

            if db_key not in csv_keys:
                try:
                    delete_sql = f"DELETE FROM {TABLE} WHERE [schedule_id] = ?"
                    cursor.execute(delete_sql, [db_schedule_id])
                    deleted_rows += cursor.rowcount
                    logging.info(f"DELETED: '{db_employee}' on {db_date} at '{db_center}' (schedule_id: {db_schedule_id})")
                except pyodbc.Error as del_ex:
                    failed_rows += 1
                    logging.error(f"Error deleting orphan record (schedule_id: {db_schedule_id}): {del_ex}")

        logging.info(f"Orphan cleanup complete. Total rows deleted: {deleted_rows}")

        # Commit the transaction to make the changes permanent
        if updated_rows > 0 or inserted_rows > 0 or deleted_rows > 0:
            conn.commit()
            logging.info(f"\nTransaction committed.")

        logging.info(f"Database update complete. Total rows updated: {updated_rows}, Total rows inserted: {inserted_rows}, Total rows deleted: {deleted_rows}")

except pyodbc.Error as ex:
    sqlstate = ex.args[0]
    logging.error(f"Database connection failed: {sqlstate}")
    logging.error(f"Rows committed before failure — updated: {updated_rows}, inserted: {inserted_rows}, deleted: {deleted_rows if 'deleted_rows' in dir() else 'N/A'}, failed: {failed_rows}")