"""Explicit initial owner provisioning. Password input/output stays outside the repository."""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from lerny.admin_models import AdminGrant
from lerny.admin_security import audit
from lerny.db import engine
from lerny.models import User
from lerny.operations import state
from lerny.security import hasher
from sqlalchemy import select
from sqlalchemy.orm import Session


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--login-id", required=True)
    parser.add_argument("--password-file", type=Path)
    parser.add_argument("--allow-cloud", action="store_true")
    args = parser.parse_args()
    import re

    login_id = args.login_id.lower()
    if not re.fullmatch(r"[a-z0-9_.@-]{3,100}", login_id):
        raise SystemExit("Invalid login id")
    if engine().url.host not in {"127.0.0.1", "localhost", "::1"} and not args.allow_cloud:
        raise SystemExit("Cloud provisioning requires explicit --allow-cloud")
    password = (
        args.password_file.read_text(encoding="utf-8").strip()
        if args.password_file
        else getpass.getpass("Temporary password: ")
    )
    if len(password) < 6:
        raise SystemExit("Temporary password is too short")
    with Session(engine()) as session:
        state(session, lock=True)
        user = session.scalar(select(User).where(User.login_id == login_id))
        if user:
            raise SystemExit("Account exists; no password or permissions changed")
        if session.scalar(select(AdminGrant.user_id).where(AdminGrant.level == "owner").limit(1)):
            raise SystemExit("An owner already exists; use the administrator UI")
        user = User(
            login_id=login_id,
            display_name="Lerny 관리자",
            role="operator",
            password_hash=hasher.hash(password),
            must_change_password=True,
        )
        session.add(user)
        session.flush()
        session.add(AdminGrant(user_id=user.id, level="owner"))
        audit(session, user, "owner_bootstrapped", user.id, outcome="succeeded")
        session.commit()
    print("Owner created; password change and MFA enrollment required on first login")


if __name__ == "__main__":
    main()
