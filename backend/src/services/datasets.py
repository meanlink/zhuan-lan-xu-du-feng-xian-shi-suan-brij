from fastapi import HTTPException
from sqlalchemy import select
from src.models import Dataset
from src.services import identity
from src.services.business import metadata
from src.utils.serialization import checksum
import math, time
def create(db, data, actor='system'):
    name=data.name.strip()
    if len(name)<2: raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
    if db.scalar(select(Dataset).where(Dataset.name==name)):
        raise HTTPException(409, '该数据批次名已存在，请修改名称')
    for index,row in enumerate(data.records):
        for c in metadata()['columns']:
            value=row.get(c['key'])
            if value is None or value=='': raise HTTPException(422, f'第 {index+1} 行缺少字段 {c["label"]}')
            if c['type']=='number':
                try:
                    if isinstance(value,bool) or not math.isfinite(float(value)): raise ValueError()
                    row[c['key']]=float(value)
                except (TypeError, ValueError, OverflowError): raise HTTPException(422, f'第 {index+1} 行 {c["label"]} 必须为有限数值')
    # Raw records are stored untouched. The ledger only records which numbers
    # exist; their person assignment is frozen later, per experiment.
    identity.ensure_numbers(db,[str(row.get('reader_id','')).strip() for row in data.records],
                            actor,reason=f'数据批次 {name} 接入')
    d=Dataset(name=name, source=data.source, records=data.records, checksum=checksum(data.records), created_at=time.time())
    db.add(d); db.flush()
    return d
