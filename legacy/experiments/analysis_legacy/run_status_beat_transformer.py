"""Complete fixed Beat Transformer evidence for a status-audit catalog.

The prepare stage reuses exact audio-hash-matched results and computes only
missing official frontend features. The infer stage runs missing features
sequentially with the pinned runner and never opens reference labels.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from inspect_inputs import sha256


def save(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')


def existing_results(roots):
    found={}
    for root in roots:
        for path in sorted(root.glob('*/result.json')):
            result=json.loads(path.read_text());digest=result['audio']['sha256']
            if digest not in found or 'beat-transformer-v2' in str(path):found[digest]=path.parent
    return found


def prepare(catalog_path,output,roots,frontend_python,threads,resume=False,reuse_only=False):
    catalog=json.loads(catalog_path.read_text())
    manifest_path=output/'manifest.json'
    if output.exists():
        if not resume or not manifest_path.is_file():raise ValueError('existing output requires --resume and a manifest')
        previous=json.loads(manifest_path.read_text())
        if previous['catalog_sha256']!=sha256(catalog_path):raise ValueError('resume catalog changed')
        prior_rows={row['id']:row for row in previous['rows']}
    else:
        output.mkdir(parents=True);(output/'results').mkdir();(output/'features').mkdir();prior_rows={}
    prior=existing_results(roots);rows=[]
    for index,track in enumerate(catalog['tracks'],1):
        if track['id'] in prior_rows:
            row=prior_rows[track['id']]
            if row['audio_sha256']!=track['input']['sha256']:raise ValueError('resume audio changed')
            if row['status']=='reused' and not (Path(row['result_dir'])/'result.json').is_file():raise ValueError('reused result disappeared')
            if row['status']=='features_ready' and sha256(row['features'])!=row['features_sha256']:raise ValueError('prepared feature changed')
            rows.append(row);print(f'{index}/{len(catalog["tracks"])} {track["id"]}: {row["status"]}',flush=True);continue
        audio=Path(track['input']['path']);digest=track['input']['sha256']
        if sha256(audio)!=digest:raise ValueError(f'{track["id"]}: audio hash mismatch')
        destination=output/'results'/track['id']
        if digest in prior:
            source=prior[digest];destination.symlink_to(source.resolve(),target_is_directory=True)
            result=json.loads((destination/'result.json').read_text())
            if result['audio']['sha256']!=digest:raise ValueError('reused result mismatch')
            row={'id':track['id'],'status':'reused','audio_sha256':digest,'result_dir':str(destination),'reused_from':str(source)}
        else:
            if reuse_only:
                row={'id':track['id'],'status':'frontend_runtime_failure','audio_sha256':digest,
                    'result_dir':str(destination),'reason':'Pinned Spleeter 2.3.2 separate() aborts with glibc double-free on this host; reproduced on a prior-success control and a 36.5-second input.'}
                rows.append(row);save(output/'manifest.json',{'schema_version':1,'catalog':str(catalog_path),
                    'catalog_sha256':sha256(catalog_path),'reference_files_opened':False,'rows':rows})
                print(f'{index}/{len(catalog["tracks"])} {track["id"]}: {row["status"]}',flush=True);continue
            feature=output/'features'/(track['id']+'.npz')
            command=[str(frontend_python),str(Path(__file__).with_name('beat_transformer_frontend.py')),
                'prepare','--audio',str(audio),'--output',str(feature),'--model-root','data/models/beat-transformer/spleeter',
                '--threads',str(threads)]
            subprocess.run(command,check=True)
            meta=json.loads(feature.with_suffix('.json').read_text())
            if meta['audio_sha256']!=digest or meta['feature_sha256']!=sha256(feature):raise ValueError('feature provenance mismatch')
            row={'id':track['id'],'status':'features_ready','audio_sha256':digest,'result_dir':str(destination),
                'features':str(feature),'features_sha256':sha256(feature)}
        rows.append(row);save(output/'manifest.json',{'schema_version':1,'catalog':str(catalog_path),
            'catalog_sha256':sha256(catalog_path),'reference_files_opened':False,'rows':rows})
        print(f'{index}/{len(catalog["tracks"])} {track["id"]}: {row["status"]}',flush=True)


def infer(output,device,threads):
    manifest_path=output/'manifest.json';manifest=json.loads(manifest_path.read_text())
    for index,row in enumerate(manifest['rows'],1):
        if row['status']=='frontend_runtime_failure':continue
        destination=Path(row['result_dir'])
        if row['status']=='reused' or destination.exists():
            if not (destination/'result.json').is_file():raise ValueError('existing result is incomplete')
            row['status']='reused' if row.get('reused_from') else 'inferred'
            continue
        feature=Path(row['features'])
        if sha256(feature)!=row['features_sha256']:raise ValueError('feature changed before inference')
        catalog=json.loads(Path(manifest['catalog']).read_text());track=next(t for t in catalog['tracks'] if t['id']==row['id'])
        command=[sys.executable,str(Path(__file__).with_name('run_beat_transformer.py')),
            '--audio',track['input']['path'],'--features',str(feature),'--output-dir',str(destination),
            '--device',device,'--threads',str(threads)]
        subprocess.run(command,check=True)
        result=json.loads((destination/'result.json').read_text())
        if result['audio']['sha256']!=row['audio_sha256']:raise ValueError('inferred result audio mismatch')
        row['status']='inferred';row['result_sha256']=sha256(destination/'result.json')
        save(manifest_path,manifest);print(f'{index}/{len(manifest["rows"])} {row["id"]}: inferred',flush=True)
    save(manifest_path,manifest)


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('prepare');a.add_argument('--catalog',type=Path,required=True);a.add_argument('--output-dir',type=Path,required=True)
    a.add_argument('--existing-root',type=Path,nargs='+',required=True);a.add_argument('--resume',action='store_true');a.add_argument('--reuse-only',action='store_true');a.add_argument('--frontend-python',type=Path,default=Path('data/cache/beat-transformer/frontend-venv/bin/python'));a.add_argument('--threads',type=int,default=2)
    b=sub.add_parser('infer');b.add_argument('--output-dir',type=Path,required=True);b.add_argument('--device',choices=('cpu','cuda'),default='cuda');b.add_argument('--threads',type=int,default=2)
    args=p.parse_args()
    if args.command=='prepare':prepare(args.catalog,args.output_dir,args.existing_root,args.frontend_python,args.threads,args.resume,args.reuse_only)
    else:infer(args.output_dir,args.device,args.threads)


if __name__=='__main__':main()
