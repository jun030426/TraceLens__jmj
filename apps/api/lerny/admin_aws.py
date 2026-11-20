"""Allowlisted EC2 control, from Vercel OIDC or an explicitly configured runtime role."""

import os
import re
import threading
from contextvars import ContextVar
from datetime import timedelta
from pathlib import Path

import boto3
import httpx
from botocore import UNSIGNED
from botocore.config import Config
from lerny.config import settings
from lerny.models import now

_lock = threading.Lock()
_cached = None
_expires = None
_key = None
request_token = ContextVar("lerny_vercel_oidc_token", default="")


def oidc_token():
    if token := request_token.get():
        return token
    if path := os.environ.get("VERCEL_OIDC_TOKEN_FILE"):
        try:
            token = Path(path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError("OIDC_TOKEN_UNAVAILABLE") from exc
        if not token:
            raise ValueError("OIDC_TOKEN_UNAVAILABLE")
        return token
    return os.environ.get("VERCEL_OIDC_TOKEN", "")


def ec2():
    global _cached, _expires, _key
    cfg = settings()
    if not cfg.admin_server_enabled or not cfg.admin_instance_id or not cfg.admin_aws_account:
        raise ValueError("SERVER_CONTROL_NOT_CONFIGURED")
    config = Config(
        connect_timeout=3, read_timeout=8, retries={"total_max_attempts": 1, "mode": "standard"}
    )
    key = (
        cfg.admin_aws_region,
        cfg.admin_aws_account,
        cfg.admin_instance_id,
        cfg.admin_aws_role_arn,
    )
    with _lock:
        if _cached and _key == key and _expires > now() + timedelta(seconds=60):
            return _cached
        session = boto3.Session(region_name=cfg.admin_aws_region)
        if cfg.admin_aws_role_arn:
            if not cfg.admin_aws_role_arn.startswith(f"arn:aws:iam::{cfg.admin_aws_account}:role/"):
                raise ValueError("INVALID_CONTROL_ROLE")
            token = oidc_token()
            if not token:
                raise ValueError("OIDC_TOKEN_UNAVAILABLE")
            sts = session.client(
                "sts",
                config=Config(
                    signature_version=UNSIGNED,
                    connect_timeout=3,
                    read_timeout=8,
                    retries={"total_max_attempts": 1},
                ),
            )
            result = sts.assume_role_with_web_identity(
                RoleArn=cfg.admin_aws_role_arn,
                RoleSessionName="lerny-admin",
                WebIdentityToken=token,
                DurationSeconds=900,
            )
            creds = result["Credentials"]
            session = boto3.Session(
                region_name=cfg.admin_aws_region,
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"],
            )
            expires = creds["Expiration"]
        else:
            if os.environ.get("VERCEL") == "1":
                raise ValueError("OIDC_ROLE_REQUIRED")
            identity = session.client("sts", config=config).get_caller_identity()
            if identity["Account"] != cfg.admin_aws_account:
                raise ValueError("AWS_PROJECT_MISMATCH")
            expires = now() + timedelta(minutes=5)
        _cached, _key, _expires = session.client("ec2", config=config), key, expires
        return _cached


def describe():
    if settings().admin_control_url:
        return bridge("describe")
    result = ec2().describe_instances(InstanceIds=[settings().admin_instance_id])
    reservation = result["Reservations"][0]
    if reservation["OwnerId"] != settings().admin_aws_account:
        raise ValueError("AWS_PROJECT_MISMATCH")
    item = reservation["Instances"][0]
    return {
        "instance_id": item["InstanceId"],
        "state": item["State"]["Name"],
        "type": item["InstanceType"],
        "region": settings().admin_aws_region,
    }


def start():
    if settings().admin_control_url:
        return bridge("start")["request_id"]
    return ec2().start_instances(InstanceIds=[settings().admin_instance_id])["ResponseMetadata"][
        "RequestId"
    ]


def stop():
    if settings().admin_control_url:
        return bridge("stop")["request_id"]
    # Normal OS shutdown only. No termination, force stop, or arbitrary command path.
    return ec2().stop_instances(InstanceIds=[settings().admin_instance_id], Force=False)[
        "ResponseMetadata"
    ]["RequestId"]


def bridge(action):
    cfg = settings()
    if not cfg.admin_server_enabled or not cfg.admin_instance_id or not cfg.admin_aws_account:
        raise ValueError("SERVER_CONTROL_NOT_CONFIGURED")
    expected = rf"https://[a-z0-9]+\.lambda-url\.{re.escape(cfg.admin_aws_region)}\.on\.aws/?"
    if not re.fullmatch(expected, cfg.admin_control_url):
        raise ValueError("INVALID_CONTROL_URL")
    token = oidc_token()
    if not token:
        raise ValueError("OIDC_TOKEN_UNAVAILABLE")
    try:
        # Do not retry power commands or forward authorization through redirects.
        response = httpx.post(cfg.admin_control_url, json={"action": action},
                              headers={"Authorization": f"Bearer {token}"},
                              timeout=httpx.Timeout(15, connect=3), follow_redirects=False)
        response.raise_for_status()
        value = response.json()
        if action == "describe" and (value.get("instance_id") != cfg.admin_instance_id
                                     or value.get("region") != cfg.admin_aws_region):
            raise ValueError("TARGET_MISMATCH")
        if action != "describe" and not value.get("request_id"):
            raise ValueError("MISSING_REQUEST_ID")
        return value
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise ValueError("SERVER_CONTROL_UNAVAILABLE") from exc
