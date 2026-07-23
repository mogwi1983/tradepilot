"""Upload Lob CSV audience file to a Lob Campaign via Lob API."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.env import load_env
from core.system_logger import get_system_logger


def upload_audience_to_lob(csv_path: Path, campaign_id: str) -> str | None:
    load_env()
    logger = get_system_logger()

    lob_key = os.getenv("LOB_API_KEY", "").strip()
    if not lob_key:
        logger.error("LobUpload", "LOB_API_KEY environment variable not set")
        return None

    if not csv_path.exists():
        logger.error("LobUpload", f"File not found: {csv_path}")
        return None

    logger.info("LobUpload", f"Starting upload of {csv_path.name} to campaign {campaign_id}")

    # Step 1: Create upload container
    url = "https://api.lob.com/v1/uploads"
    headers = {
        "Authorization": requests.auth._basic_auth_str(lob_key, ""),
        "Content-Type": "application/json",
    }
    payload = {
        "campaignId": campaign_id,
        "requiredAddressColumnMapping": {
            "name": "name",
            "address_line1": "address_line1",
            "address_city": "address_city",
            "address_state": "address_state",
            "address_zip": "address_zip",
        },
        "optionalAddressColumnMapping": {
            "company": "company",
        },
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code not in (200, 201):
            logger.error("LobUpload", f"Create upload failed HTTP {resp.status_code}: {resp.text}")
            return None
        upload_data = resp.json()
        upload_id = upload_data.get("id")
        logger.info("LobUpload", f"Upload container created: {upload_id}")

        # Step 2: POST the file content
        file_url = f"https://api.lob.com/v1/uploads/{upload_id}/file"
        files = {"file": (csv_path.name, open(csv_path, "rb"), "text/csv")}
        auth = (lob_key, "")
        resp_file = requests.post(file_url, auth=auth, files=files, timeout=60)
        if resp_file.status_code not in (200, 201, 202):
            logger.error("LobUpload", f"Upload file failed HTTP {resp_file.status_code}: {resp_file.text}")
            return None

        logger.info("LobUpload", f"File {csv_path.name} uploaded successfully. Upload ID: {upload_id}")

        # Step 3: Poll status
        status_url = f"https://api.lob.com/v1/uploads/{upload_id}"
        for _ in range(12):
            time.sleep(5)
            s_resp = requests.get(status_url, auth=auth, timeout=15)
            if s_resp.status_code == 200:
                state = s_resp.json().get("state")
                logger.info("LobUpload", f"Upload state: {state}")
                if state in ("Validated", "Ready", "Complete"):
                    return upload_id
                if state == "Failed":
                    logger.error("LobUpload", f"Upload failed: {s_resp.text}")
                    return None

        return upload_id

    except Exception as exc:
        logger.error("LobUpload", f"Lob API Upload exception: {exc}")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload Lob-ready CSV audience file to a Lob Campaign")
    parser.add_argument("--file", required=True, help="Path to exported Lob CSV file")
    parser.add_argument("--campaign-id", required=True, help="Lob Campaign ID (cmp_xxx)")
    args = parser.parse_args()

    file_path = Path(args.file)
    upload_id = upload_audience_to_lob(file_path, args.campaign_id)
    if upload_id:
        print(f"Success: Uploaded {file_path.name} to Lob. Upload ID: {upload_id}")
    else:
        print(f"Failed to upload {file_path.name} to Lob.")


if __name__ == "__main__":
    main()
