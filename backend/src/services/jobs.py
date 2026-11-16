import time
from fastapi import HTTPException
from redis import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.config.settings import REDIS_URL
from src.models import Dataset, Job
from src.services import identity
from src.services.business import metadata
def create(db, data, user):
    d=db.get(Dataset,data.dataset_id)
    if not d: raise HTTPException(404,'数据批次不存在')
    key=(data.operation_key or '').strip() or None
    if key:
        existing=db.scalar(select(Job).where(Job.operation_key==key))
        if existing is not None:
            if existing.dataset_id!=data.dataset_id or existing.name!=data.name.strip():
                raise HTTPException(409,'该操作号已用于另一笔试验，请使用新的操作号')
            return existing, True
    allowed={p['key']:p for p in metadata().get('parameters',[])}
    if set(data.params)-set(allowed): raise HTTPException(422,'包含未知分析参数')
    params={k:p['default'] for k,p in allowed.items()}
    params.update(data.params)
    for param_key,p in allowed.items():
        v=params[param_key]
        if p['type']=='number':
            try:
                v=float(v)
                if not (p.get('min',-1e9)<=v<=p.get('max',1e9)): raise ValueError()
                params[param_key]=v
            except (ValueError,TypeError): raise HTTPException(422, f'{p["label"]} 超出范围或非数值')
        elif str(v) not in [str(o['value']) for o in p.get('options',[])]:
            raise HTTPException(422,f'{p["label"]} 不是有效选项')
    # Freeze one complete identity version together with the experiment. A
    # concurrent merge/split either lands fully before or after this snapshot.
    snapshot=identity.snapshot_for_records(
        db,d.records,user.email,
        expected_version=data.expected_identity_version,
        reason=f'创建试验 {data.name.strip()}',
    )
    j=Job(name=data.name,dataset_id=data.dataset_id,params=params,created_by=user.id,
          created_at=time.time(),status='queued',operation_key=key,
          identity_version=snapshot['version'],
          identity_fingerprint=snapshot['fingerprint'],
          identity_snapshot=snapshot)
    db.add(j)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing=db.scalar(select(Job).where(Job.operation_key==key)) if key else None
        if existing is None:
            raise HTTPException(409,'试验创建与另一笔身份或试验修改相撞，请刷新后重试')
        return existing, True
    except Exception:
        db.rollback()
        raise
    return j, False
def enqueue(job_id):
    try:
        r=Redis.from_url(REDIS_URL); r.rpush('analysis:queue',job_id); r.close()
    except Exception:
        pass # SQL queued status is the durable fallback
