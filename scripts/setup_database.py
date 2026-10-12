"""Create a loopback-only development PostgreSQL cluster; never use trust auth."""
import json
import os
from pathlib import Path
import secrets
import subprocess

import psycopg
from psycopg import sql

ROOT = Path(os.environ.get('LERNY_RUNTIME_ROOT', Path.home() / 'LernyData'))
BIN = ROOT / 'tools/postgresql-17/pgsql/bin'
DATA = ROOT / 'data/postgres'
SECRET = ROOT / 'secrets'


def command(*args):
    subprocess.run([str(BIN / args[0]), *map(str, args[1:])], check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)


if __name__ == '__main__':
    SECRET.mkdir(parents=True, exist_ok=True)
    admin_file = SECRET / 'postgres.json'
    if not admin_file.exists():
        admin_file.write_text(json.dumps({'password': secrets.token_urlsafe(32)}))
    password = json.loads(admin_file.read_text())['password']
    if not (DATA / 'PG_VERSION').exists():
        pwfile = SECRET / 'initdb-password'
        pwfile.write_text(password)
        try:
            command('initdb.exe', '-D', DATA, '-U', 'postgres', '--encoding=UTF8',
                    '--locale=C', '--auth=scram-sha-256', '--pwfile', pwfile)
        finally:
            pwfile.unlink(missing_ok=True)
        with (DATA / 'postgresql.conf').open('a') as f:
            f.write("\nlisten_addresses='127.0.0.1'\nport=55432\n")
    status = subprocess.run([str(BIN / 'pg_ctl.exe'), '-D', str(DATA), 'status'],
                            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if status.returncode:
        command('pg_ctl.exe', '-D', DATA, '-l', ROOT / 'data/postgres.log', 'start', '-w')
    config_file = SECRET / 'app.json'
    config = json.loads(config_file.read_text()) if config_file.exists() else {}
    app_password = config.get('database_url', '').split('lerny:')[-1].split('@')[0]
    if not app_password:
        app_password = secrets.token_urlsafe(32)
    with psycopg.connect(host='127.0.0.1', port=55432, user='postgres', password=password,
                         dbname='postgres', autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname='lerny'").fetchone():
            conn.execute(sql.SQL('CREATE ROLE lerny LOGIN PASSWORD {}').format(sql.Literal(app_password)))
        for name in ('lerny', 'lerny_test'):
            if not conn.execute('SELECT 1 FROM pg_database WHERE datname=%s', (name,)).fetchone():
                conn.execute(sql.SQL('CREATE DATABASE {} OWNER lerny').format(sql.Identifier(name)))
    config['database_url'] = f'postgresql+psycopg://lerny:{app_password}@127.0.0.1:55432/lerny'
    config_file.write_text(json.dumps(config, indent=2))
    print('PostgreSQL ready on 127.0.0.1:55432; credentials in external secrets directory.')
