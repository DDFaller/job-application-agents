import hashlib,json,re,shutil
from pathlib import Path
from datetime import datetime,timezone

src=Path('/home/falluba/Documents/job-search/sources').resolve()
root=Path('/home/falluba/Documents/job-search/master-curriculum')
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
out=root/f'audit-v006-{stamp}'
out.mkdir(parents=True)
(out/'snapshots').mkdir()
files=['identity.md','education.md','experience.md','projects.md','skills.md','languages.md']
sources=[]; facts=[]; byprefix={'ID':'identity','EDU':'education','EXP':'experience','PROJ':'project','SKILL':'skill','LANG':'language'}
for name in files:
    p=src/name; data=p.read_bytes(); (out/'snapshots'/name).write_bytes(data)
    h=hashlib.sha256(data).hexdigest(); sp=(out/'snapshots'/name).resolve()
    sources.append({'path':str(p),'sha256':h,'snapshot_path':str(sp),'snapshot_sha256':hashlib.sha256(data).hexdigest(),'pages':None})
    for line in data.decode().splitlines():
        m=re.match(r'- \[MC-([A-Z]+)-\d+\] (.+)$',line)
        if m:
            facts.append({'id':f'E{len(facts)+1:03d}','category':byprefix[m.group(1)],'claim':m.group(2),'source_path':str(p),'quote':line,'page':None})
ids_by=lambda pred:[f['id'] for f in facts if pred(f)]
identity=facts
def find(txt): return [f['id'] for f in facts if txt in f['claim']]
name=find('Name:'); headline=find('Headline:'); email=find('Email:'); phones=find('Phone:'); langs=ids_by(lambda f:f['category']=='language')
evidence={'schema_version':2,'extraction_status':'complete','candidate':{'name':'Daniel Faller','headline':'Software Engineer','location':None,'contact':[f['claim'].split(': ',1)[1] for f in facts if f['claim'].startswith('Email:') or f['claim'].startswith('Phone:')],'languages':[f['claim'] for f in facts if f['category']=='language']},'sources':sources,'facts':facts,'field_evidence':{'candidate.name':name,'candidate.headline':headline},'missing_fields':[],'warnings':[],'extracted_at':datetime.now(timezone.utc).isoformat()}
for i in range(len(evidence['candidate']['contact'])): evidence['field_evidence'][f'candidate.contact.{i}']=email+phones if i==0 else phones[i-1:i]
for i in range(len(langs)): evidence['field_evidence'][f'candidate.languages.{i}']=[langs[i]]
ep=out/'candidate-evidence.json'; ep.write_text(json.dumps(evidence,indent=2,ensure_ascii=False)+'\n')
print(out)
