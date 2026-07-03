import json
import os
import tempfile
import requests
from google.oauth2 import service_account
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
DRIVE_API = "https://www.googleapis.com/drive/v3/files"


def _get_authed_session(credentials_json=None, credentials_file=None):
    if credentials_json:
        try:
            info = json.loads(credentials_json)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"GDRIVE_CREDENTIALS_JSON is not valid JSON: {e}. "
                f"First 50 chars: {credentials_json[:50]!r}"
            )
        required = {"client_email", "token_uri", "private_key", "type"}
        missing = required - set(info.keys())
        if missing:
            raise ValueError(
                f"GDRIVE_CREDENTIALS_JSON missing fields: {missing}. "
                f"Keys found: {list(info.keys())}"
            )
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES
        )
    elif credentials_file:
        creds_path = credentials_file
        if not os.path.isabs(creds_path):
            creds_path = os.path.join(os.path.dirname(__file__), creds_path)

        if not os.path.exists(creds_path):
            raise FileNotFoundError(
                f"Service account credentials file not found: {creds_path}"
            )

        creds = service_account.Credentials.from_service_account_file(
            creds_path, scopes=SCOPES
        )
    else:
        raise ValueError(
            "Provide GDRIVE_CREDENTIALS_JSON (JSON string) or GDRIVE_CREDENTIALS_FILE (file path)"
        )

    creds.refresh(Request())
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {creds.token}"
    return session


def list_csv_filenames(folder_id, credentials_json=None, credentials_file=None):
    """Return list of CSV filenames in a Google Drive folder (no download)."""
    if not folder_id:
        return []

    session = _get_authed_session(
        credentials_json=credentials_json, credentials_file=credentials_file
    )

    query = f"'{folder_id}' in parents and mimeType='text/csv' and trashed=false"
    resp = session.get(
        DRIVE_API,
        params={"q": query, "fields": "files(name)", "orderBy": "name"},
    )
    resp.raise_for_status()
    return [f["name"] for f in resp.json().get("files", [])]


def get_csv_from_gdrive(folder_id, credentials_json=None, credentials_file=None):
    """Download all CSV files from a Google Drive folder to a temp directory.

    Returns the temp directory path (or single file path if only one CSV).
    """
    if not folder_id:
        raise ValueError("Google Drive folder ID is not set. Check your .env file.")

    session = _get_authed_session(
        credentials_json=credentials_json, credentials_file=credentials_file
    )

    query = f"'{folder_id}' in parents and mimeType='text/csv' and trashed=false"
    resp = session.get(
        DRIVE_API,
        params={"q": query, "fields": "files(id,name)", "orderBy": "name"},
    )
    resp.raise_for_status()
    files = resp.json().get("files", [])

    if not files:
        raise FileNotFoundError(
            f"No CSV files found in Google Drive folder: {folder_id}"
        )

    download_dir = tempfile.mkdtemp(prefix="zenoti_gdrive_")

    for f in files:
        dl_resp = session.get(
            f"{DRIVE_API}/{f['id']}", params={"alt": "media"}, stream=True
        )
        dl_resp.raise_for_status()
        local_path = os.path.join(download_dir, f["name"])
        with open(local_path, "wb") as fh:
            for chunk in dl_resp.iter_content(chunk_size=8192):
                fh.write(chunk)
        print(f"Downloaded from Drive: {f['name']}")

    if len(files) == 1:
        return os.path.join(download_dir, files[0]["name"])

    return download_dir
