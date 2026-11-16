from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from src.config.database import get_db
from src.middlewares.auth import current_user
from src.models import Dataset, Job, Report, Audit
from src.services import identity
from src.services.business import metadata
router=APIRouter()
@router.get('/meta')
def meta():return metadata()
@router.get('/overview')
def overview(db=Depends(get_db),user=Depends(current_user)):
    ledger=identity.ledger(db)
    return {'datasets':db.scalar(select(func.count()).select_from(Dataset)), 'records':sum(len(d.records) for d in db.scalars(select(Dataset))), 'jobs':db.scalar(select(func.count()).select_from(Job)), 'approved':db.scalar(select(func.count()).select_from(Job).where(Job.approved==True)), 'reports':db.scalar(select(func.count()).select_from(Report)), 'identity_version':ledger['version'], 'identity_numbers':ledger['numbers'], 'identity_people':ledger['people'], 'identity_merged':ledger['merged_groups']}
@router.get('/audits')
def audits(db=Depends(get_db),user=Depends(current_user)):
    return [{'id':a.id,'actor':a.actor,'action':a.action,'detail':a.detail,'at':a.at} for a in db.scalars(select(Audit).order_by(Audit.id.desc()).limit(50))]
