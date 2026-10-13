"""Private Supabase Storage. Service credentials are used only inside the backend."""

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote

import httpx

from lerny.config import settings


class StorageUnavailable(Exception):
    pass


def request(method, path, **kwargs):
    config = settings()
    key = config.supabase_service_key.get_secret_value()
    headers = {"apikey": key}
    # New sb_secret keys are API keys, not JWTs. Legacy service_role keys are JWTs.
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = "Bearer " + key
    headers.update(kwargs.pop("headers", {}))
    try:
        with httpx.Client(timeout=90, trust_env=False) as client:
            result = client.request(
                method,
                config.supabase_url.rstrip("/") + "/storage/v1" + path,
                headers=headers,
                **kwargs,
            )
            result.raise_for_status()
            return result
    except httpx.HTTPError:
        # Never include signed URLs, keys, or HTTP request dumps in errors/logs.
        raise StorageUnavailable("Storage request failed") from None


def object_path(key):
    return quote(settings().storage_bucket, safe="") + "/" + quote(key, safe="/")


def signed_upload(key):
    response = request("POST", "/object/upload/sign/" + object_path(key), json={}).json()
    path = response["url"]
    if not path.startswith("/object/upload/sign/"):
        raise StorageUnavailable("Invalid signed upload path")
    return settings().supabase_url.rstrip("/") + "/storage/v1" + path


def signed_download(key, filename):
    result = request("POST", "/object/sign/" + object_path(key), json={"expiresIn": 60}).json()
    path = result["signedURL"]
    if not path.startswith("/object/sign/"):
        raise StorageUnavailable("Invalid signed download path")
    return (
        settings().supabase_url.rstrip("/")
        + "/storage/v1"
        + path
        + ("&" if "?" in path else "?")
        + "download="
        + quote(filename, safe="")
    )


def download(key, limit):
    # Stream with a strict bound; never trust client-declared size or Content-Length.
    config = settings()
    credential = config.supabase_service_key.get_secret_value()
    headers = {"apikey": credential}
    if not credential.startswith("sb_secret_"):
        headers["Authorization"] = "Bearer " + credential
    try:
        with (
            httpx.Client(timeout=90, trust_env=False) as client,
            client.stream(
                "GET",
                config.supabase_url.rstrip("/") + "/storage/v1/object/" + object_path(key),
                headers=headers,
            ) as response,
        ):
            response.raise_for_status()
            data = bytearray()
            for block in response.iter_bytes(1024 * 1024):
                data.extend(block)
                if len(data) > limit:
                    raise ValueError("FILE_TOO_LARGE")
            return bytes(data)
    except httpx.HTTPError:
        raise StorageUnavailable("Storage download failed") from None


def put(key, content):
    request(
        "POST",
        "/object/" + object_path(key),
        content=content,
        headers={"Content-Type": "application/octet-stream", "x-upsert": "false"},
    )


def delete_object(key):
    request(
        "DELETE", "/object/" + quote(settings().storage_bucket, safe=""), json={"prefixes": [key]}
    )


@contextmanager
def source_file(version):
    if settings().deployment == "local":
        yield settings().runtime_root / "data/files" / version.object_key
        return
    # Function scratch space only: durable sources always live in Storage.
    with TemporaryDirectory(prefix="lerny-source-") as directory:
        path = Path(directory) / Path(version.object_key).name
        path.write_bytes(download(version.object_key, 100 * 1024 * 1024))
        yield path


def ready():
    result = request("GET", "/bucket/" + quote(settings().storage_bucket, safe="")).json()
    return result.get("public") is False
