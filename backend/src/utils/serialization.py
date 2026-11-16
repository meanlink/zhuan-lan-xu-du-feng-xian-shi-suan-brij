import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at}
def identity_basis(j):
    snapshot=j.identity_snapshot or {}
    groups=snapshot.get('groups',[])
    return {
        'version':j.identity_version,
        'fingerprint':j.identity_fingerprint,
        'frozen':bool(snapshot),
        'basis':(f'身份版本 v{j.identity_version}' if snapshot else '未冻结身份台账（旧任务）'),
        'groups':len(groups),
        'merged_groups':sum(1 for g in groups if g.get('merged')),
    }
def job_dict(j):
    data={k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at']}
    data['identity_version']=j.identity_version
    data['identity_fingerprint']=j.identity_fingerprint
    data['identity_basis']=identity_basis(j)
    return data
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
