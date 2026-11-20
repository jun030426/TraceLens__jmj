"""Current server summary and bounded history, with real local DB and MFA authorization."""
from datetime import timedelta
import pytest
from sqlalchemy import select, func
from lerny import admin_aws, operations
from lerny.admin_models import OperationsWorker
from lerny.config import settings
from lerny.models import now
from test_admin import authorize, client
from test_identity_courses import login


@pytest.fixture(autouse=True)
def configured_server(monkeypatch):
    monkeypatch.setattr(settings(), 'admin_instance_id', 'i-current')
    def blocked(): raise AssertionError('Overview must not make an AWS call')
    monkeypatch.setattr(admin_aws,'describe',blocked)


@pytest.mark.asyncio
async def test_overview_is_three_kinds_and_ignores_unlinked_helpers(app_db):
    app,db=app_db
    moment=now()
    for i in range(120):
        db.add(OperationsWorker(id=f'old-{i}',kind='material',server_id='i-current',last_seen_at=moment-timedelta(days=1,seconds=i),ready=True))
    db.add_all([
        OperationsWorker(id='scheduler-helper',kind='material',server_id=None,last_seen_at=moment,ready=True),
        OperationsWorker(id='other-server',kind='code',server_id='i-other',last_seen_at=moment,ready=True),
        OperationsWorker(id='not-ready',kind='code',server_id='i-current',last_seen_at=moment,ready=False),
        OperationsWorker(id='ready-video',kind='video',server_id='i-current',last_seen_at=moment,ready=True),
    ])
    control=operations.state(db);control.server_hold=False;db.commit()
    async with client(app) as c:
        await login(c,'operator1');authorize(db)
        r=await c.get('/api/v1/admin/overview');assert r.status_code==200,r.text
        assert 'no-store' in r.headers['cache-control']
        summary=r.json(); workers=summary['workers']
        assert [w['kind'] for w in workers]==['material','code','video']
        assert [w['status'] for w in workers]==['stale','not_ready','online']
        assert summary['worker_history_count']==122
        assert workers[0]['responding']==0 and workers[1]['ready']==0 and workers[2]['ready']==1
        control.server_hold=True;db.commit()
        assert (await c.get('/api/v1/admin/overview')).json()['workers'][0]['status']=='waiting_response'
        assert db.scalar(select(func.count()).select_from(OperationsWorker))==124


@pytest.mark.asyncio
async def test_empty_history_and_recent_ready_worker_are_not_hidden_by_newer_unready(app_db):
    app,db=app_db
    async with client(app) as c:
        await login(c,'operator1');authorize(db)
        result=(await c.get('/api/v1/admin/overview')).json()
        assert len(result['workers'])==3 and result['worker_history_count']==0
        assert all(w['last_seen_at'] is None and w['status']=='waiting_response' for w in result['workers'])
        moment=now()
        db.add_all([
            OperationsWorker(id='ready',kind='material',server_id='i-current',last_seen_at=moment-timedelta(seconds=10),ready=True),
            OperationsWorker(id='restarting',kind='material',server_id='i-current',last_seen_at=moment,ready=False),
        ]);db.commit()
        worker=(await c.get('/api/v1/admin/overview')).json()['workers'][0]
        assert worker['status']=='online' and worker['responding']==2 and worker['ready']==1


@pytest.mark.asyncio
async def test_history_is_filtered_paged_stable_and_read_only(app_db):
    app,db=app_db
    moment=now()-timedelta(hours=1)
    for i in range(37):
        db.add(OperationsWorker(id=f'process-{i:02}',kind='material' if i%2 else 'code',server_id='i-current',last_seen_at=moment,ready=True))
    db.add(OperationsWorker(id='exclude',kind='video',server_id=None,last_seen_at=now(),ready=True));db.commit()
    async with client(app) as c:
        await login(c,'operator1');authorize(db)
        ids=[]
        for offset in range(0,37,5):
            r=await c.get('/api/v1/admin/workers',params={'offset':offset})
            assert r.status_code==200 and 'no-store' in r.headers['cache-control']
            page=r.json();assert page['total']==37 and len(page['items'])<=5
            ids += [x['id'] for x in page['items']]
        assert ids==[f'process-{i:02}' for i in reversed(range(37))]
        filtered=(await c.get('/api/v1/admin/workers?kind=material')).json()
        assert filtered['total']==18 and all(x['kind']=='material' for x in filtered['items'])
        assert (await c.get('/api/v1/admin/workers?limit=21')).status_code==422
        assert (await c.get('/api/v1/admin/workers?offset=-1')).status_code==422
        assert (await c.get('/api/v1/admin/workers?kind=invalid')).status_code==422
        assert (await c.get('/api/v1/admin/workers?offset=99')).json()['items']==[]
        assert db.scalar(select(func.count()).select_from(OperationsWorker))==38


@pytest.mark.asyncio
@pytest.mark.parametrize('name',['student1','teacher1','operator1'])
async def test_history_requires_admin_and_mfa(app_db,name):
    app,db=app_db
    async with client(app) as c:
        await login(c,name)
        assert (await c.get('/api/v1/admin/workers')).status_code==403
