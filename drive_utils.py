# drive_utils.py

import os
import io
import json
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

import config

logger = logging.getLogger(__name__)


def _load_service_account_credentials():
    if not config.SERVICE_ACCOUNT_ENV:
        raise RuntimeError("SERVICE_ACCOUNT_JSON env var is missing.")
    
    # Scope for full read/write access
    scopes = ['https://www.googleapis.com/auth/drive']

    try:
        info = json.loads(config.SERVICE_ACCOUNT_ENV)
        return service_account.Credentials.from_service_account_info(info, scopes=scopes)
    except json.JSONDecodeError as e:
        raise RuntimeError("SERVICE_ACCOUNT_JSON is not valid JSON.") from e


def get_drive_service():
    try:
        creds = _load_service_account_credentials()
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        logger.error(f"Failed to create Drive service: {e}")
        return None


def get_folder_id(service, parent_id, folder_name):
    """Finds a folder's ID by name within a parent folder using a direct query."""
    try:
        query = (
            f"'{parent_id}' in parents and "
            f"mimeType = 'application/vnd.google-apps.folder' and "
            f"name = '{folder_name}' and "
            f"trashed = false"
        )
        logger.info(f"Searching for folder with query: {query}")
        
        results = service.files().list(
            q=query,
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            corpora="allDrives"
        ).execute()
        
        logger.info(f"Google Drive API response for '{folder_name}': {results}")
        items = results.get('files', [])
        
        if items:
            return items[0]['id']
        else:
            logger.warning(f"Folder '{folder_name}' not found inside parent '{parent_id}'.")
            return None
            
    except HttpError as e:
        logger.error(f"An error occurred while searching for folder '{folder_name}': {e}")
    return None


def list_items(service, parent_id, item_type="folders"):
    mime_type_query = (
        "mimeType = 'application/vnd.google-apps.folder'"
        if item_type == "folders"
        else "mimeType != 'application/vnd.google-apps.folder'"
    )
    try:
        query = f"'{parent_id}' in parents and {mime_type_query} and trashed = false"
        results = service.files().list(
            q=query, 
            pageSize=100, 
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        return results.get('files', [])
    except HttpError as e:
        logger.error(f"An error occurred while listing items in folder '{parent_id}': {e}")
        return []


def download_file(service, file_id):
    try:
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
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


def upload_file(service, folder_id, file_name, file_handle, mimetype='application/octet-stream'):
    try:
        file_metadata = {'name': file_name, 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_handle, mimetype=mimetype, resumable=True)
        file = service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, webViewLink',
            supportsAllDrives=True
        ).execute()
        return file
    except HttpError as e:
        logger.error(f"An error occurred during file upload: {e}")
        return None


def count_all_files_for_branch(service, branch_id):
    """Recursively counts all 'Notes' and 'Assignments' files within a branch."""
    notes_count = 0
    assignments_count = 0
    
    subjects = list_items(service, branch_id, "folders")
    
    for subject in subjects:
        notes_folder_id = get_folder_id(service, subject['id'], "Notes")
        if notes_folder_id:
            notes_files = list_items(service, notes_folder_id, "files")
            notes_count += len(notes_files)
            
        assignments_folder_id = get_folder_id(service, subject['id'], "Assignments")
        if assignments_folder_id:
            assignments_files = list_items(service, assignments_folder_id, "files")
            assignments_count += len(assignments_files)
            
    return notes_count, assignments_count
