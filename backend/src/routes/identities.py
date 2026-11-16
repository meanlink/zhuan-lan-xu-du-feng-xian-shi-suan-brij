from fastapi import APIRouter, Depends, HTTPException
from src.config.database import get_db
from src.middlewares.auth import current_user, can_write
from src.schemas.identity import MergeInput, SplitInput, RegisterInput
from src.services import identity
router=APIRouter(prefix='/identities')
@router.get('/ledger')
def ledger(db=Depends(get_db),u=Depends(current_user)):
    return identity.ledger(db)
@router.get('/operations')
def operations(db=Depends(get_db),u=Depends(current_user)):
    return identity.operations(db)
@router.get('/conflicts')
def conflicts(db=Depends(get_db),u=Depends(current_user)):
    return identity.conflicts(db)
@router.get('/jobs')
def jobs(db=Depends(get_db),u=Depends(current_user)):
    return identity.jobs_basis(db)
@router.get('/numbers/{number}')
def number_detail(number:str,db=Depends(get_db),u=Depends(current_user)):
    return identity.number_detail(db,number)
@router.post('/merge')
def merge(data:MergeInput,db=Depends(get_db),u=Depends(can_write)):
    return identity.merge(db,u.email,data.numbers,data.expected_version,data.reason,data.operation_key)
@router.post('/split')
def split(data:SplitInput,db=Depends(get_db),u=Depends(can_write)):
    return identity.split(db,u.email,data.number,data.expected_version,data.reason,data.operation_key)
@router.post('/register')
def register(data:RegisterInput,db=Depends(get_db),u=Depends(can_write)):
    version=identity.ensure_numbers(db,data.numbers,u.email,data.reason or '手动登记')
    db.commit()
    return {'version':version}
