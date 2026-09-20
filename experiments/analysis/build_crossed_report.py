"""Build a readable crossed-model report without pooling reference cohorts."""
import argparse
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from inspect_inputs import sha256


CELLS = [('beat_this__clock_current', 'Beat This / current', '#54a0c4'),
         ('beat_this__clock_candidates_selected', 'Beat This / candidates', '#226443'),
         ('beat_transformer__clock_current', 'Beat Transformer / current', '#e49d56'),
         ('beat_transformer__clock_candidates_selected', 'Beat Transformer / candidates', '#a34b52')]


def build(reports, catalogs, output):
    if output.exists():
        raise ValueError('new output directory required')
    entries = {t['id']: t for p in catalogs for t in json.loads(p.read_text())['tracks']}
    output.mkdir(parents=True)
    blocks = []
    for p in reports:
        report = json.loads(p.read_text())
        if not report['complete']:
            raise ValueError('crossed report must be complete')
        for row in report['tracks']:
            reference_record = entries[row['id']]['reference']
            if sha256(reference_record['path']) != reference_record['sha256']:
                raise ValueError('reference changed')
            reference = json.loads(Path(reference_record['path']).read_text())
            fig, ax = plt.subplots(figsize=(12, 3.5), layout='constrained')
            table = []
            for key, label, color in CELLS:
                method = row['methods'][key]
                metrics = method['metrics']
                for_tol = metrics['tempo_changes_500ms']
                matches = for_tol.get('full_change_scores')
                count = (f"{matches['true_positives']}/{matches['true_positives']+matches['false_negatives']}"
                         if matches else '미평가')
                hundred = metrics['tempo_changes_100ms'].get('full_change_scores')
                hundred_text = f"{hundred['true_positives']}/{hundred['true_positives']+hundred['false_negatives']}" if hundred else '미평가'
                extra = matches['false_positives'] if matches else '—'
                output_kind = ('후보 없음' if not method['prediction']['beats_seconds'] else
                               '템포 지도 후보' if method.get('clock') else '박 이벤트만')
                table.append(f"<tr><td>{label}</td><td>{output_kind}</td><td>{100*metrics['event_20ms']['f1']:.2f}</td>"
                             f"<td>{100*metrics['event_70ms']['f1']:.2f}</td><td>{count}</td><td>{hundred_text}</td><td>{extra}</td></tr>")
                if method.get('clock'):
                    segments = method['clock']['segments']
                    ax.step([s['start_seconds'] for s in segments]+[segments[-1]['end_seconds']],
                            [s['pulse_rate_per_minute'] for s in segments]+[segments[-1]['pulse_rate_per_minute']],
                            where='post', label=label, color=color, alpha=.85, linewidth=1.2)
            if reference.get('tempo_events'):
                events = reference['tempo_events']
                ax.step([e['time_seconds'] for e in events]+[entries[row['id']]['duration_seconds']],
                        [e['bpm_quarter'] for e in events]+[events[-1]['bpm_quarter']],
                        where='post', label='Reference quarter BPM', color='#191e31', linestyle='--', linewidth=1.4)
            ax.set(xlabel='Unchanged source time (seconds)', ylabel='Proposed pulses / minute', title=row['id'])
            ax.grid(alpha=.2); ax.legend(fontsize=8, ncol=3)
            image_name=row['id']+'.png';fig.savefig(output/image_name,dpi=140);plt.close(fig)
            entry = entries[row['id']]
            qualification = entry.get('qualification_status', 'Rendered MIDI development reference; musical intent qualification separate')
            blocks.append(f'<section><h2>{html.escape(row["id"])}</h2><p>{html.escape(row.get("cohort",row["dataset"]))} · {html.escape(qualification)}</p>'
                          f'<table><thead><tr><th>조건</th><th>출력</th><th>박 F1 ±20ms</th><th>박 F1 ±70ms</th><th>변경 ±500ms</th><th>변경 ±100ms</th><th>추가 변경 ±500ms</th></tr></thead><tbody>{"".join(table)}</tbody></table>'
                          f'<img src="{image_name}" alt="기준과 네 조건의 템포 지도"><p class="small">변경 점수는 위치와 변경 전후 BPM(±0.1)을 함께 비교합니다. 곡 전체 박자표의 정확도나 무수정 완성률을 나타내지 않습니다.</p></section>')
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>모델 × 지도 재구성 비교</title>
<style>body{font:15px/1.7 system-ui,sans-serif;max-width:1220px;margin:35px auto;padding:0 20px;background:#f3f5f8;color:#253044}section{background:white;padding:22px;border-radius:12px;margin:22px 0}h1{font-size:25px}h2{font-size:20px}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:9px;border-bottom:1px solid #dde3ed}th{background:#e8eef5}img{max-width:100%}.notice{background:#fff0ce;padding:16px}.small{font-size:13px;color:#596577}a{color:#17625b}</style>
<h1>음향 모델 × 템포 지도 재구성</h1><p>독립 모델의 정보와 새로운 후보 생성의 효과를 분리해 비교한 결과입니다.</p>
<p class="notice">아래는 정답 없이 선택한 결과입니다. 정답으로 최선의 후보를 고른 oracle 점수는 자동 성능에 포함하지 않았습니다. 새 방법은 실험 후보이며, 실제 사용자 수정 시간은 아직 측정하지 않았습니다.</p>
<p>공개 합성 회귀와 제작자 제공 음원은 서로 다른 평가 집단입니다. 자료의 의미를 유지하기 위해 전체를 하나의 평균으로 합치지 않았습니다.</p>__BLOCKS__</html>'''
    (output/'index.html').write_text(page.replace('__BLOCKS__',''.join(blocks)),encoding='utf-8')
    (output/'manifest.json').write_text(json.dumps({'generator_sha256':sha256(__file__),
        'reports':[{'path':str(p),'sha256':sha256(p)} for p in reports]},indent=2)+'\n')
    return output/'index.html'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reports',type=Path,nargs='+',required=True)
    p.add_argument('--catalogs',type=Path,nargs='+',required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args();print(build(args.reports,args.catalogs,args.output_dir))


if __name__=='__main__':main()
