"""Tests for the cleanup_attachments tool and the scheduler cron job."""
import os

from backend.tools import cleanup_attachments as ct
from models.db import db


def _make_agent(agent_id, is_super=False):
    db.create_agent({
        'id': agent_id, 'name': agent_id, 'system_prompt': '',
        'is_super': is_super,
    })
    return agent_id


def _store(agent_id, body=b'X', name='hello.txt', tmp_path=None):
    target_dir = os.path.join(str(tmp_path), 'data', 'attachments', agent_id, 's1')
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, f"f_{name}")
    with open(path, 'wb') as f:
        f.write(body)
    aid = db.save_attachment(
        agent_id=agent_id, session_id='s1',
        filename=os.path.basename(path), file_path=path,
        original_filename=name, mime_type='text/plain',
        file_type='document', size_bytes=len(body),
    )
    return aid, path


def _backdate(attachment_id, days):
    with db._connect() as conn:
        conn.execute(
            "UPDATE attachments SET created_at = datetime('now', ?) WHERE id = ?",
            (f"-{days} days", attachment_id),
        )


def test_non_super_agent_denied(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_agent('plain_agent', is_super=False)
    result = ct.execute({'id': 'plain_agent'}, {})
    assert 'error' in result
    assert 'super agent' in result['error'].lower()


def test_super_agent_runs_cleanup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_agent('su_agent', is_super=True)
    aid_old, path_old = _store('su_agent', b'OLD' * 100, name='old.txt', tmp_path=tmp_path)
    aid_new, path_new = _store('su_agent', b'NEW' * 100, name='new.txt', tmp_path=tmp_path)
    _backdate(aid_old, days=10)
    result = ct.execute({'id': 'su_agent', 'is_super': True}, {'older_than_days': 7})
    assert 'result' in result
    payload = result['result']
    assert payload['deleted_count'] == 1
    assert payload['freed_bytes'] > 0
    assert payload['older_than_days'] == 7
    assert db.get_attachment(aid_old) is None
    assert db.get_attachment(aid_new) is not None
    assert not os.path.exists(path_old)
    assert os.path.exists(path_new)


def test_super_agent_zero_days_deletes_backdated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_agent('su2', is_super=True)
    aid, path = _store('su2', b'data', tmp_path=tmp_path)
    # Backdate by 1 second so it's "older than 0 days" (strictly less than now).
    _backdate(aid, days=0)  # no-op for now; ensure SQL strict-less-than catches anything older
    with db._connect() as conn:
        conn.execute(
            "UPDATE attachments SET created_at = datetime('now', '-1 second') WHERE id = ?",
            (aid,),
        )
    result = ct.execute({'id': 'su2', 'is_super': True}, {'older_than_days': 0})
    assert 'result' in result
    assert result['result']['deleted_count'] == 1
    assert db.get_attachment(aid) is None
    assert not os.path.exists(path)


def test_invalid_older_than_days_string(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_agent('su3', is_super=True)
    result = ct.execute({'id': 'su3', 'is_super': True}, {'older_than_days': 'oops'})
    assert 'error' in result
    assert 'Invalid' in result['error']


def test_invalid_older_than_days_negative(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _make_agent('su4', is_super=True)
    result = ct.execute({'id': 'su4', 'is_super': True}, {'older_than_days': -1})
    assert 'error' in result


def test_scheduler_registers_attachments_cleanup_job():
    """Confirm Scheduler.start() registers the built-in cleanup cron job."""
    from backend.scheduler import Scheduler
    sched = Scheduler()
    sched.start()
    try:
        job_ids = {j.id for j in sched._scheduler.get_jobs()}
        assert 'builtin:attachments_cleanup' in job_ids
    finally:
        sched.shutdown()


def test_scheduler_cleanup_invocation(tmp_path, monkeypatch):
    """The private _cleanup_expired_attachments() method calls into db and logs."""
    monkeypatch.chdir(tmp_path)
    _make_agent('su5', is_super=True)
    aid_old, path_old = _store('su5', b'OLD', name='old2.txt', tmp_path=tmp_path)
    _backdate(aid_old, days=10)
    from backend.scheduler import Scheduler
    sched = Scheduler()
    # Direct call without starting APScheduler.
    sched._cleanup_expired_attachments()
    assert db.get_attachment(aid_old) is None
    assert not os.path.exists(path_old)
