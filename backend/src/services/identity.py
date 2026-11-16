"""Identity merge ledger.

A *number* is a login/account observed in samples. A *group* is one real
person. Numbers move between groups over time; every membership period is kept
append-only, and every change produces a new complete ledger version.

Concurrency contract:
  * callers pass the ledger version they observed (`expected_version`);
  * a stale version rejects the whole operation, never part of it;
  * `operation_key` makes retries idempotent: the same key replays the stored
    result instead of booking a second change.
"""
import time

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from src.config.database import Session
from src.models import (
    Audit, Dataset, IdentityGroup, IdentityMembership, IdentityNumber,
    IdentityOperation, IdentityState,
)
from src.utils.serialization import checksum

STATE_ID = 1
SAMPLE_NUMBER_FIELD = 'reader_id'


def _now():
    return time.time()


def _state(db, lock=False):
    statement = select(IdentityState).where(IdentityState.id == STATE_ID)
    if lock:
        # FOR UPDATE plus populate_existing: a concurrent commit that landed
        # since this session last read state must be visible, otherwise the
        # version check would compare against a stale in-memory row.
        statement = statement.with_for_update().execution_options(populate_existing=True)
    state = db.scalar(statement)
    if state is None:
        state = IdentityState(id=STATE_ID, version=0, updated_at=_now())
        db.add(state)
        db.flush()
    return state


def current_version(db):
    return _state(db).version


def _group_code(group_id):
    return f'P-{group_id:04d}'


def _add_groups(db, count, note='', created_version=0):
    groups = [IdentityGroup(code=None, created_version=created_version,
                            created_at=_now(), note=note) for _ in range(count)]
    db.add_all(groups)
    db.flush()
    for group in groups:
        group.code = _group_code(group.id)
    db.flush()
    return groups


def _add_operation(db, *, kind, actor, reason, numbers, affected,
                   expected_version, version, operation_key):
    reason = (reason or '')[:300]
    operation = IdentityOperation(
        operation_key=operation_key, version=version,
        expected_version=expected_version, kind=kind, actor=actor,
        reason=reason, numbers=list(numbers), affected=list(affected),
        fingerprint='', created_at=_now(),
    )
    db.add(operation)
    db.flush()
    operation.fingerprint = checksum({
        'kind': kind, 'numbers': sorted(numbers), 'reason': reason,
        'expected_version': expected_version,
    })
    db.flush()
    return operation


def _audit_reject(db, actor, kind, detail, message, status=409):
    """Rejections leave no ledger change; the reason goes to the audit trail."""
    current = detail.get('current_version')
    try:
        db.rollback()
    except Exception:
        pass
    try:
        with Session() as audit_db:
            audit_db.add(Audit(actor=actor, action=f'identity.{kind}.rejected',
                               detail=dict(detail, reason=message), at=_now()))
            audit_db.commit()
    except Exception:
        pass
    headers = {'X-Identity-Version': str(current)} if current is not None else None
    raise HTTPException(status, message, headers=headers)


def _load_numbers(db, numbers, lock=False):
    statement = select(IdentityNumber).where(IdentityNumber.number.in_(numbers))
    if lock:
        statement = statement.with_for_update()
    found = {row.number: row for row in db.scalars(statement)}
    missing = [n for n in numbers if n not in found]
    return found, missing


def _normalize_numbers(values):
    cleaned, seen = [], set()
    for value in values:
        number = str(value or '').strip()
        if not number:
            continue
        if len(number) > 120:
            raise HTTPException(422, '号码长度不能超过120个字符')
        if number not in seen:
            seen.add(number)
            cleaned.append(number)
    if not cleaned:
        raise HTTPException(422, '至少提供一个有效号码')
    return cleaned


def _register_missing(db, numbers, actor, reason):
    """Register unseen numbers as independent people. Caller holds the lock."""
    state = _state(db, lock=True)
    # Locking read: a concurrent registration committed just before we took
    # the state lock must be visible, otherwise we would insert duplicates.
    found, missing = _load_numbers(db, numbers, lock=True)
    if not missing:
        return state.version, []
    version = state.version + 1
    groups = _add_groups(db, len(missing), note='号码首次接入', created_version=version)
    created = []
    for number, group in zip(sorted(missing), groups):
        record = IdentityNumber(number=number, current_group_id=group.id,
                                first_version=version, updated_version=version,
                                created_at=_now())
        db.add(record)
        db.flush()
        db.add(IdentityMembership(number_id=record.id, group_id=group.id,
                                  from_version=version, to_version=None,
                                  reason=reason, created_at=_now()))
        created.append({'number': number, 'group': group.code})
    state.version = version
    state.updated_at = _now()
    operation = _add_operation(
        db, kind='register', actor=actor, reason=reason, numbers=sorted(missing),
        affected=created, expected_version=state.version - 1, version=version,
        operation_key=f'register-{version}-{checksum(sorted(missing))[:12]}',
    )
    db.flush()
    for membership in db.scalars(select(IdentityMembership).where(
            IdentityMembership.number_id.in_(
                select(IdentityNumber.id).where(IdentityNumber.number.in_(sorted(missing)))),
            IdentityMembership.operation_id.is_(None),
            IdentityMembership.from_version == version)):
        membership.operation_id = operation.id
    db.add(Audit(actor=actor, action='identity.register',
                 detail={'version': version, 'numbers': len(missing)}, at=_now()))
    return version, created


def ensure_numbers(db, numbers, actor, reason='批次接入'):
    """Ensure roster membership for numbers; may bump the ledger version."""
    version, _ = _register_missing(db, _normalize_numbers(numbers), actor, reason)
    db.flush()
    return version


def snapshot_for_records(db, records, actor, expected_version=None, reason='分析任务创建'):
    """Freeze one complete identity version for an experiment.

    The state row is locked for the whole snapshot, so a concurrent merge
    either happens entirely before or entirely after this read.
    """
    numbers = [str(row.get(SAMPLE_NUMBER_FIELD, '')).strip() for row in records]
    numbers = [n for n in numbers if n]
    state = _state(db, lock=True)
    if expected_version is not None and int(expected_version) != state.version:
        _audit_reject(
            db, actor, 'snapshot',
            {'expected_version': int(expected_version), 'current_version': state.version},
            f'身份台账已更新（当前版本 {state.version}，提交时看到的是 {expected_version}），'
            '本次试验未创建，请刷新台账后重试。',
        )
    if numbers:
        # New numbers absent from the ledger become independent people. This
        # happens under the same lock, so no merge can interleave. A brand-new
        # ledger version is accepted here only because no merge/split happened:
        # the version was bumped solely by this experiment registering numbers.
        _register_missing(db, numbers, actor, reason)
        state = _state(db, lock=True)
    version = state.version
    mapping, groups = _snapshot_rows(db)
    fingerprint = checksum({'version': version, 'numbers': sorted(mapping.items())})
    return {
        'version': version,
        'fingerprint': fingerprint,
        'numbers': mapping,
        'groups': groups,
        'frozen_at': _now(),
    }


def _snapshot_rows(db):
    rows = db.execute(
        select(IdentityNumber.number, IdentityGroup.code, IdentityNumber.current_group_id)
        .join(IdentityGroup, IdentityGroup.id == IdentityNumber.current_group_id)
        .order_by(IdentityNumber.number)
    ).all()
    mapping = {number: code for number, code, _ in rows}
    grouped = {}
    for number, code, group_id in rows:
        grouped.setdefault((group_id, code), []).append(number)
    groups = [{'code': code, 'id': group_id, 'numbers': sorted(members),
               'merged': len(members) > 1}
              for (group_id, code), members in sorted(grouped.items())]
    return mapping, groups


def _check_operation_replay(db, operation_key, kind, numbers, reason, expected_version):
    operation = db.scalar(select(IdentityOperation).where(
        IdentityOperation.operation_key == operation_key))
    if operation is None:
        return None
    fingerprint = checksum({
        'kind': kind, 'numbers': sorted(numbers), 'reason': reason,
        'expected_version': expected_version,
    })
    if operation.fingerprint != fingerprint:
        raise HTTPException(409, '该操作号已用于另一笔身份修改，请使用新的操作号')
    return operation


def _operation_view(operation):
    return {
        'id': operation.id, 'operation_key': operation.operation_key,
        'version': operation.version, 'expected_version': operation.expected_version,
        'kind': operation.kind, 'actor': operation.actor, 'reason': operation.reason,
        'numbers': operation.numbers, 'number_count': len(operation.numbers or []),
        'affected': operation.affected,
        'fingerprint': operation.fingerprint, 'created_at': operation.created_at,
    }


def _finish(db, operation):
    db.add(Audit(actor=operation.actor, action=f'identity.{operation.kind}',
                 detail={'version': operation.version, 'numbers': operation.numbers,
                         'reason': operation.reason}, at=_now()))
    db.commit()
    return {'operation': _operation_view(operation), 'version': operation.version}


def merge(db, actor, numbers, expected_version, reason='', operation_key=None):
    numbers = _normalize_numbers(numbers)
    if len(numbers) < 2:
        raise HTTPException(422, '归并至少需要两个号码')
    reason = (reason or '').strip()
    operation_key = operation_key or f'merge-{checksum(sorted(numbers))}-{expected_version}'
    if len(operation_key) > 120:
        raise HTTPException(422, '操作号过长')
    try:
        state = _state(db, lock=True)
        replay = _check_operation_replay(db, operation_key, 'merge', numbers, reason, expected_version)
        if replay is not None:
            return {'operation': _operation_view(replay), 'version': replay.version, 'replayed': True}
        if state.version != expected_version:
            _audit_reject(
                db, actor, 'merge',
                {'expected_version': expected_version, 'current_version': state.version,
                 'numbers': numbers},
                f'身份台账已更新（当前版本 {state.version}，提交时看到的是 {expected_version}），'
                '整笔归并未执行，请刷新后重试。',
            )
        found, missing = _load_numbers(db, numbers, lock=True)
        if missing:
            _audit_reject(db, actor, 'merge',
                          {'numbers': numbers, 'missing': missing},
                          f'号码不存在：{"、".join(missing)}', status=422)
        group_ids = []
        for number in numbers:
            if found[number].current_group_id not in group_ids:
                group_ids.append(found[number].current_group_id)
        if len(group_ids) < 2:
            _audit_reject(
                db, actor, 'merge',
                {'numbers': numbers, 'group': group_ids[0] if group_ids else None},
                '这些号码已属于同一身份，无需归并', status=409,
            )
        version = state.version + 1
        target_id = group_ids[0]
        target = db.get(IdentityGroup, target_id)
        source_ids = group_ids[1:]
        moving = list(db.scalars(select(IdentityNumber).where(
            IdentityNumber.current_group_id.in_(source_ids)).order_by(IdentityNumber.number)))
        operation = _add_operation(
            db, kind='merge', actor=actor, reason=reason, numbers=numbers,
            affected=[{'number': n.number,
                       'from': db.get(IdentityGroup, n.current_group_id).code,
                       'to': target.code} for n in moving],
            expected_version=expected_version, version=version,
            operation_key=operation_key,
        )
        for number in moving:
            old_membership = db.scalar(select(IdentityMembership).where(
                IdentityMembership.number_id == number.id,
                IdentityMembership.to_version.is_(None)))
            if old_membership is not None:
                old_membership.to_version = version
                if old_membership.operation_id is None:
                    old_membership.operation_id = operation.id
            number.current_group_id = target.id
            number.updated_version = version
            db.add(IdentityMembership(number_id=number.id, group_id=target.id,
                                      from_version=version, to_version=None,
                                      operation_id=operation.id, reason=reason,
                                      created_at=_now()))
        state.version = version
        state.updated_at = _now()
        db.flush()
        return _finish(db, operation)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '身份台账同时被其他操作修改，请刷新后重试')
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise


def split(db, actor, number, expected_version, reason='', operation_key=None):
    numbers = _normalize_numbers([number])
    number = numbers[0]
    reason = (reason or '').strip()
    operation_key = operation_key or f'split-{number}-{expected_version}'
    if len(operation_key) > 120:
        raise HTTPException(422, '操作号过长')
    try:
        state = _state(db, lock=True)
        replay = _check_operation_replay(db, operation_key, 'split', numbers, reason, expected_version)
        if replay is not None:
            return {'operation': _operation_view(replay), 'version': replay.version, 'replayed': True}
        if state.version != expected_version:
            _audit_reject(
                db, actor, 'split',
                {'expected_version': expected_version, 'current_version': state.version,
                 'number': number},
                f'身份台账已更新（当前版本 {state.version}，提交时看到的是 {expected_version}），'
                '整笔拆分未执行，请刷新后重试。',
            )
        found, missing = _load_numbers(db, [number], lock=True)
        if missing:
            _audit_reject(db, actor, 'split', {'number': number},
                          f'号码不存在：{number}', status=422)
        record = found[number]
        source = db.get(IdentityGroup, record.current_group_id)
        siblings = db.scalar(select(func.count()).select_from(IdentityNumber).where(
            IdentityNumber.current_group_id == source.id))
        if siblings <= 1:
            _audit_reject(
                db, actor, 'split', {'number': number, 'group': source.code},
                f'号码 {number} 已是独立身份（{source.code}），无需拆分', status=409,
            )
        version = state.version + 1
        new_group = _add_groups(db, 1, note=f'由 {source.code} 拆出',
                                created_version=version)[0]
        operation = _add_operation(
            db, kind='split', actor=actor, reason=reason, numbers=[number],
            affected=[{'number': number, 'from': source.code, 'to': new_group.code}],
            expected_version=expected_version, version=version,
            operation_key=operation_key,
        )
        old_membership = db.scalar(select(IdentityMembership).where(
            IdentityMembership.number_id == record.id,
            IdentityMembership.to_version.is_(None)))
        if old_membership is not None:
            old_membership.to_version = version
            if old_membership.operation_id is None:
                old_membership.operation_id = operation.id
        record.current_group_id = new_group.id
        record.updated_version = version
        db.add(IdentityMembership(number_id=record.id, group_id=new_group.id,
                                  from_version=version, to_version=None,
                                  operation_id=operation.id, reason=reason,
                                  created_at=_now()))
        state.version = version
        state.updated_at = _now()
        db.flush()
        return _finish(db, operation)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '身份台账同时被其他操作修改，请刷新后重试')
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise


def ledger(db, include_empty=True):
    state = _state(db)
    numbers = list(db.scalars(select(IdentityNumber).order_by(IdentityNumber.number)))
    groups = list(db.scalars(select(IdentityGroup).order_by(IdentityGroup.id)))
    by_group = {}
    for number in numbers:
        by_group.setdefault(number.current_group_id, []).append(
            {'number': number.number, 'since_version': number.updated_version}
        )
    rows = []
    for group in groups:
        members = by_group.get(group.id, [])
        if not members and not include_empty:
            continue
        rows.append({
            'id': group.id, 'code': group.code, 'note': group.note,
            'created_version': group.created_version,
            'numbers': [m['number'] for m in members],
            'members': members,
            'empty': not members,
            'merged': len(members) > 1,
        })
    return {
        'version': state.version,
        'updated_at': state.updated_at,
        'numbers': len(numbers),
        'people': sum(1 for row in rows if not row['empty']),
        'merged_groups': sum(1 for row in rows if row['merged']),
        'groups': rows,
    }


def number_detail(db, number):
    number = str(number or '').strip()
    record = db.scalar(select(IdentityNumber).where(IdentityNumber.number == number))
    if record is None:
        raise HTTPException(404, '号码不在身份台账中')
    current = db.get(IdentityGroup, record.current_group_id)
    memberships = list(db.scalars(select(IdentityMembership).where(
        IdentityMembership.number_id == record.id).order_by(IdentityMembership.from_version)))
    history = []
    for membership in memberships:
        group = db.get(IdentityGroup, membership.group_id)
        operation = db.get(IdentityOperation, membership.operation_id) if membership.operation_id else None
        history.append({
            'group_code': group.code, 'group_id': group.id,
            'from_version': membership.from_version,
            'to_version': membership.to_version,
            'reason': membership.reason,
            'operation_id': membership.operation_id,
            'operation_kind': operation.kind if operation else 'baseline',
            'actor': operation.actor if operation else 'system',
            'at': membership.created_at,
        })
    usage = []
    for dataset in db.scalars(select(Dataset).order_by(Dataset.id)):
        count = sum(1 for row in dataset.records
                    if str(row.get(SAMPLE_NUMBER_FIELD, '')).strip() == number)
        if count:
            usage.append({'dataset_id': dataset.id, 'dataset_name': dataset.name,
                          'rows': count})
    return {
        'number': record.number,
        'current_group': {
            'id': current.id, 'code': current.code, 'note': current.note,
            'numbers': sorted(n.number for n in db.scalars(select(IdentityNumber).where(
                IdentityNumber.current_group_id == current.id))),
        },
        'history': history,
        'datasets': usage,
    }


def operations(db, limit=100):
    rows = db.scalars(select(IdentityOperation)
                      .order_by(IdentityOperation.id.desc()).limit(limit))
    return [_operation_view(row) for row in rows]


def conflicts(db, limit=50):
    rows = db.scalars(select(Audit).where(Audit.action.like('identity.%rejected'))
                      .order_by(Audit.id.desc()).limit(limit))
    return [{'id': row.id, 'actor': row.actor, 'action': row.action,
             'detail': row.detail, 'at': row.at} for row in rows]


def jobs_basis(db, limit=100):
    from src.models import Job
    rows = db.scalars(select(Job).order_by(Job.id.desc()).limit(limit))
    return [{
        'id': job.id, 'name': job.name, 'status': job.status,
        'approved': job.approved,
        'identity_version': job.identity_version,
        'identity_fingerprint': job.identity_fingerprint,
        'has_snapshot': bool(job.identity_snapshot),
        'merged_groups': sum(1 for group in (job.identity_snapshot or {}).get('groups', [])
                             if group.get('merged')),
        'created_at': job.created_at,
    } for job in rows]
