"""Private S3 media, authorized by the same course checks as document uploads.

The web runtime uses its short-lived Vercel identity through a restricted bridge.
The dedicated worker uses its instance role. No AWS credentials reach the browser.
"""
import re
from pathlib import Path

import boto3
import httpx
from botocore.config import Config

from lerny.config import settings

PREFIX = "s3media/"


def enabled():
    cfg = settings()
    return bool(cfg.media_storage_enabled and cfg.media_storage_url and cfg.media_storage_bucket
                and re.fullmatch(r"\d{12}", cfg.media_storage_account))


def media_id(key):
    match = re.fullmatch(r"s3media/([a-f0-9-]{36})\.mp4", key)
    if not match:
        raise ValueError("INVALID_MEDIA_KEY")
    return match[1]


def bridge(action, **body):
    from lerny.admin_aws import oidc_token
    cfg = settings()
    if not enabled():
        raise ValueError("MEDIA_STORAGE_NOT_CONFIGURED")
    if not re.fullmatch(rf"https://[a-z0-9]+\.lambda-url\.{re.escape(cfg.media_storage_region)}\.on\.aws/?", cfg.media_storage_url):
        raise ValueError("INVALID_MEDIA_STORAGE_URL")
    token = oidc_token()
    if not token:
        raise ValueError("OIDC_TOKEN_UNAVAILABLE")
    try:
        with httpx.Client(timeout=httpx.Timeout(240, connect=5), trust_env=False, follow_redirects=False) as client:
            response = client.post(cfg.media_storage_url, json={"action": action, **body},
                                   headers={"Authorization": "Bearer " + token})
        if response.status_code in {400, 409, 413, 422}:
            code = response.json().get("error")
            if code in {"INVALID_MP4", "MEDIA_SIZE_MISMATCH", "MEDIA_UPLOAD_INCOMPLETE", "MEDIA_UPLOAD_EXPIRED"}:
                raise ValueError(code)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, KeyError, TypeError):
        raise ValueError("MEDIA_STORAGE_UNAVAILABLE") from None


def download_to(key, path, limit):
    cfg = settings()
    if not cfg.dedicated_worker:
        raise ValueError("MEDIA_DEDICATED_WORKER_REQUIRED")
    identifier = media_id(key)
    client = boto3.Session(region_name=cfg.media_storage_region).client("s3", config=Config(
        connect_timeout=5, read_timeout=90, retries={"total_max_attempts": 3, "mode": "standard"}))
    response = client.get_object(Bucket=cfg.media_storage_bucket, Key=f"media/{identifier}.mp4",
                                 ExpectedBucketOwner=cfg.media_storage_account)
    with response["Body"] as body:
        if response["ContentLength"] > limit:
            raise ValueError("FILE_TOO_LARGE")
        total = 0
        with Path(path).open("wb") as target:
            for chunk in iter(lambda: body.read(1024 * 1024), b""):
                total += len(chunk)
                if total > limit:
                    raise ValueError("FILE_TOO_LARGE")
                target.write(chunk)
        if total != response["ContentLength"]:
            raise ValueError("MEDIA_SIZE_MISMATCH")


def signed_download(key, filename):
    return bridge("download", id=media_id(key), filename=filename)["url"]
