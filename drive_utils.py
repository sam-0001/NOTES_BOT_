# drive_utils.py

import os
import io
import json
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

import config # Import variables from config.py

logger = logging.getLogger(__name__)


def _load_service_account_credentials():
    """
    Loads service account credentials from an environment variable,
    which can be either a file path or a raw JSON string.
    """
    if not config.SERVICE_ACCOUNT_ENV:
        raise RuntimeError("SERVICE_ACCOUNT_JSON env var is missing.")

    scopes = ['https://www.googleapis.com/auth/drive.readonly']

    if os.path.exists(config.SERVICE_ACCOUNT_ENV):
        return service_account.Credentials.from_service_account_file(
            config.SERVICE_ACCOUNT_ENV, scopes=scopes
        )

    try:
        info = json.loads(config.SERVICE_ACCOUNT_ENV)
        return service_account.Credentials.from_service_account_info(info, scopes=scopes)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            "SERVICE_ACCOUNT_JSON is neither a valid file path nor valid JSON."
        ) from e


def get_drive_service():
    """Authenticates and returns the Google Drive service object."""
    try:
        creds = _load_service_account_credentials()
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        logger.error(f"Failed to create Drive service: {e}")
        return None


def get_folder_id(service, parent_id, folder_name):
    """Finds a folder's ID by name within a parent folder (case-insensitive)."""
    try:
        query = (
            f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' "
            "and trashed = false"
        )
        results = service.files().list(q=query, fields="files(id, name)").execute()
        items = results.get('files', [])
        for item in items:
            if item['name'].lower() == folder_name.lower():
                return item['id']
    except HttpError as e:
        logger.error(f"An error occurred while searching for folder '{folder_name}': {e}")
    return None


def list_items(service, parent_id, item_type="folders"):
    """Lists folders or files within a given parent folder."""
    mime_type_query = (
        "mimeType = 'application/vnd.google-apps.folder'"
        if item_type == "folders"
        else "mimeType != 'application/vnd.google-apps.folder'"
    )
    try:
        query = f"'{parent_id}' in parents and {mime_type_query} and trashed = false"
        results = service.files().list(q=query, pageSize=100, fields="files(id, name)").execute()
        return results.get('files', [])
    except HttpError as e:
        logger.error(f"An error occurred while listing items in folder '{parent_id}': {e}")
        return []


def download_file(service, file_id):
    """Downloads a file's content into a BytesIO object."""
    try:
        request = service.files().get_media(fileId=file_id)
        file_handle = io.BytesIO()
        downloader = MediaIoBaseDownload(file_handle, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        file_handle.seek(0)
        return file_handle
    except HttpError as e:
        logger.error(f"An error occurred while downloading file ID '{file_id}': {e}")
        return None
