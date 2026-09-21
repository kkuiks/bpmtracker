"""Package a named four-map listening comparison, retaining source sample time.

The page loads original music and pre-rendered equal-timbre quarter click WAVs.
It does not calculate a new map, stretch audio or claim a human listening result.
Serve the containing workspace over a local HTTP server to enable Web Audio.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import urllib.parse

import soundfile as sf


def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def local_asset(url, base):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError('listening assets must be local relative paths without queries')
    path=(base/urllib.parse.unquote(parsed.path)).resolve()
    if not path.is_file():raise ValueError(f'missing listening asset: {path}')
    return path


def build(bundle_path, output):
    bundle_path,output=Path(bundle_path).resolve(),Path(output).resolve()
    if output.exists() or output.with_suffix(output.suffix+'.build.json').exists():
        raise ValueError('output page and build audit must be new')
    original=json.loads(bundle_path.read_text());bundle=copy.deepcopy(original)
    source=bundle['source'];music=local_asset(source['audio_url'],bundle_path.parent)
    info=sf.info(music)
    if (info.samplerate,info.frames)!=(source['sample_rate'],source['sample_frames']):
        raise ValueError('music frame count/rate differs from declared source')
    if abs(info.duration-source['duration_seconds'])>1e-8 or sha256(music)!=source['sha256']:
        raise ValueError('music duration or hash differs from declared source')
    variants=bundle['variants']
    if len(variants)!=4 or len({v['id'] for v in variants})!=4:
        raise ValueError('exactly four distinct named variants required')
    checks=[]
    rewrite=lambda path:urllib.parse.quote(os.path.relpath(path,output.parent),safe='/')
    source['audio_url']=rewrite(music)
    for variant in variants:
        click=local_asset(variant['click_url'],bundle_path.parent);click_info=sf.info(click)
        if (click_info.samplerate,click_info.frames,click_info.channels,click_info.subtype)!=(info.samplerate,info.frames,1,'PCM_16'):
            raise ValueError(f'{variant["id"]}: click must be PCM16 mono with exact source frames/rate')
        digest=sha256(click)
        if variant.get('click_sha256') and variant['click_sha256']!=digest:
            raise ValueError(f'{variant["id"]}: click hash mismatch')
        events=variant['beats_seconds']
        if any(not math.isfinite(t) or t<0 or t>info.duration for t in events) or any(b<=a for a,b in zip(events,events[1:])):
            raise ValueError('beat times must increase within unchanged source duration')
        coverage=variant.get('coverage',{'start':0.,'end':info.duration})
        if not 0<=coverage['start']<=coverage['end']<=info.duration:
            raise ValueError('invalid reference coverage')
        variant['click_url']=rewrite(click);variant['click_sha256']=digest
        for field in ('map_url','midi_url'):
            if variant.get(field):
                asset=local_asset(variant[field],bundle_path.parent)
                digest_key=field.replace('_url','_sha256')
                asset_hash=sha256(asset)
                if variant.get(digest_key) and variant[digest_key]!=asset_hash:
                    raise ValueError(f'{variant["id"]}: {field} hash mismatch')
                variant[field]=rewrite(asset);variant[digest_key]=asset_hash
        checks.append({'id':variant['id'],'click_sha256':digest,'frames':click_info.frames,
                       'sample_rate':click_info.samplerate,'beat_event_count':len(events)})
    if bundle.get('original_creator_click'):
        asset=local_asset(bundle['original_creator_click']['audio_url'],bundle_path.parent)
        bundle['original_creator_click']['audio_url']=rewrite(asset)
    template=Path(__file__).with_name('one_song_listening.html').read_text()
    payload=json.dumps(bundle,ensure_ascii=False,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(template.replace('__ONE_SONG_BUNDLE__',payload))
    if sha256(music)!=source['sha256']:raise ValueError('source changed during page packaging')
    report={'schema_version':1,'page':str(output),'bundle':str(bundle_path),
            'bundle_sha256':sha256(bundle_path),'source_sha256':source['sha256'],
            'template_sha256':sha256(Path(__file__).with_name('one_song_listening.html')),
            'source_frames':info.frames,'source_sample_rate':info.samplerate,
            'source_audio_modified':False,'source_time_offset_seconds':0,
            'click_checks':checks,'human_listening_performed':False}
    audit=output.with_suffix(output.suffix+'.build.json')
    with audit.open('x') as handle:json.dump(report,handle,indent=2);handle.write('\n')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',required=True,type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    print(json.dumps(build(args.bundle,args.output or args.bundle.parent/'listening.html'),indent=2))


if __name__=='__main__':main()
