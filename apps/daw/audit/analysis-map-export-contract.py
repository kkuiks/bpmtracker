"""Run after tempo-map-contract.cjs --output fixtures.json. No audio/model imports.

Execute the canonical worker's pure geometry functions using only the standard
library. The fixtures carry independently integrated source beat times/accents;
check both the original analysis and applied project, plus legacy fixed clocks.
"""
from pathlib import Path
import argparse,ast,copy,hashlib,json,math
parser=argparse.ArgumentParser(description='Check exported original/project clocks against independent source beat fixtures.')
parser.add_argument('fixtures',type=Path)
parser.add_argument('--output',type=Path)
args=parser.parse_args()
worker=Path(__file__).resolve().parents[1]/'backend/worker.py'
tree=ast.parse(worker.read_text());names={'analysis_geometry','musical_map','geometry'}
ns={'math':math};exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),str(worker),'exec'),ns)
def beats(regions,left,right):
 rows=[]
 for r in regions:
  start=max(left,r['start']);end=min(right,r['end']);step=60/r['bpm']*4/r['denominator'];tick=math.ceil((start-r['phase']-1e-8)/step)
  while r['phase']+tick*step < end-1e-8:
   rows.append({'time':r['phase']+tick*step,'strong':tick%r['numerator']==0});tick+=1
 return rows
cases=json.loads(args.fixtures.read_text())['fixtures'];rows=[]
for c in cases:
 scopes={}
 for name in ['original_analysis','applied_project']:
  regions=ns['analysis_geometry'](c['project']) if name=='original_analysis' else ns['geometry'](c['project'])
  actual=beats(regions,c['from'],c['to']);expected=c['expectedBeats']
  assert len(actual)==len(expected),(c['id'],name,'beat count')
  errors=[abs(a['time']-b['time']) for a,b in zip(actual,expected)]
  assert max(errors,default=0)<=1/48000,(c['id'],name,'time')
  assert all(a['strong']==b['strong'] for a,b in zip(actual,expected)),(c['id'],name,'bar emphasis')
  scopes[name]={'regions':len(regions),'beats':len(actual),'maxErrorSeconds':max(errors,default=0)}
 rows.append({'id':c['id'],'passed':True,'scopes':scopes})
legacy={'clips':[{'id':'clip','start':2,'sourceStart':1,'duration':5}], 'clocks':[{'id':'fixed','clipId':'clip','sourceStart':0,'sourceEnd':10,'values':{'bpm':123.5,'numerator':3,'denominator':4,'offset':.137}}], 'analyses':[]}
regions=ns['analysis_geometry'](legacy)
assert regions==[{'id':'fixed','start':2,'end':7,'phase':1.137,'bpm':123.5,'numerator':3,'denominator':4,'offset':.137}]
attached=copy.deepcopy(cases[2]['project'])
expected=ns['analysis_geometry'](attached)
detached=copy.deepcopy(attached)
for clock in detached['clocks']:
 clip=next(c for c in detached['clips'] if c['id']==clock['clipId'])
 clock['projectOrigin']=clip['start']-clip['sourceStart']
detached['clips']=[]
assert ns['analysis_geometry'](detached)==expected
negative=copy.deepcopy(detached)
for clock in negative['clocks']:clock['projectOrigin']-=2
shifted=[{**r,'start':max(0,r['start']-2),'end':r['end']-2,'phase':r['phase']-2} for r in expected if r['end']>2]
actual=ns['analysis_geometry'](negative)
assert len(actual)==len(shifted)
for a,b in zip(actual,shifted):
 for key,value in b.items():
  if isinstance(value,(int,float)):assert abs(a[key]-value)<1e-8
  else:assert a[key]==value
unknown=copy.deepcopy(detached)
for clock in unknown['clocks']:clock.pop('projectOrigin')
assert ns['analysis_geometry'](unknown)==[]
invalid=json.loads(json.dumps(cases[0]['project']));invalid['analyses']=[]
try:ns['analysis_geometry'](invalid)
except ValueError:pass
else:raise AssertionError('Missing original map must fail explicitly')
report={'passed':len(rows),'total':len(rows),'rows':rows,'legacyFixedRegionPreserved':True,'detachedMapLastPlacementPreserved':True,'negativeStartClippedWithoutPhaseLoss':True,'unknownPlacementNotInvented':True,'missingOriginalMapRejected':True,'workerSha256':hashlib.sha256(worker.read_bytes()).hexdigest(),'freshNeuralCalls':0,'decoderCalls':0}
if args.output:args.output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
