"""Render a standalone Korean audit reader and exportable metric figures."""
import argparse
import html
from pathlib import Path
import re

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np

from build_status_reanalysis_report import COHORTS, NAMES
from reanalyze_status_paths import read


def markdown_html(text):
    lines=text.splitlines();out=[];table=[]
    def flush():
        if not table:return
        cells=[[html.escape(v.strip()) for v in row.strip('|').split('|')] for row in table]
        out.append('<div class="table"><table><thead><tr>'+''.join('<th>'+v+'</th>' for v in cells[0])+'</tr></thead><tbody>')
        for row in cells[2:]:out.append('<tr>'+''.join('<td>'+v+'</td>' for v in row)+'</tr>')
        out.append('</tbody></table></div>');table.clear()
    for line in lines:
        if line.startswith('|'):table.append(line);continue
        flush()
        if line.startswith('# '):out.append('<h1>'+html.escape(line[2:])+'</h1>')
        elif line.startswith('## '):out.append('<h2>'+html.escape(line[3:])+'</h2>')
        elif line:out.append('<p>'+html.escape(line)+'</p>')
    flush();return '\n'.join(out)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report-dir',type=Path,required=True);args=p.parse_args()
    root=args.report_dir;s=read(root/'summary.json')
    font=Path('/mnt/c/Windows/Fonts/malgun.ttf')
    if font.exists():font_manager.fontManager.addfont(str(font));plt.rcParams['font.family']=font_manager.FontProperties(fname=str(font)).get_name()
    plt.rcParams['axes.unicode_minus']=False
    methods=['official','legacy_dbn_clock','meter_free_clock','clock_candidates_selected','phase_after_prior_2']
    cohorts=['babyslakh','groove','ntm_user_reference','forestry_creator','forestry_observed_click','walker']
    values={(r['cohort'],r['method']):r for r in s['cohort_results'] if r['model']=='beat_this'}
    fig,axes=plt.subplots(1,2,figsize=(15,6),sharey=True,layout='constrained')
    colors=['#64748b','#2563eb','#0d9488','#d97706','#a855f7'];x=np.arange(len(cohorts));width=.15
    for ax,tol in zip(axes,['20ms','70ms']):
        for i,m in enumerate(methods):
            ys=[100*values[(c,m)]['beat_'+tol+'_macro_f1'] for c in cohorts]
            ax.bar(x+(i-2)*width,ys,width,color=colors[i],label=NAMES[m])
        ax.set_title('박 위치 허용 오차 '+tol);ax.set_ylim(0,105);ax.set_xticks(x,[COHORTS[c] for c in cohorts],rotation=20,ha='right')
        ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True);ax.set_ylabel('곡별 F1 평균 (%)')
    fig.suptitle('같은 기존 방법도 표본 집단과 허용 오차에 따라 결과가 다름\nBeat This · 채택 참조38개 · 전곡 성공률이 아님',fontsize=14)
    axes[0].legend(fontsize=8,loc='lower left');fig.savefig(root/'cohort-comparison.png',dpi=160);fig.savefig(root/'cohort-comparison.svg');plt.close(fig)
    ids=['ntm_sleeping-with-sirens_an-ending-in-itself','ntm_archspire_liminal-cypher','ntm_state-champs_common-sense','ntm_kami-kehoe_die-4-u']
    ntm={(r['id'],r['method']):r for r in s['ntm_rows']};shown=methods[:4]
    fig,ax=plt.subplots(figsize=(11,5.8),layout='constrained');x=np.arange(4);width=.19
    for i,m in enumerate(shown):
        ys=[100*ntm[(tid,m)]['beat_20ms_f1'] for tid in ids]
        bars=ax.bar(x+(i-1.5)*width,ys,width,label=NAMES[m],color=colors[i]);ax.bar_label(bars,fmt='%.1f',fontsize=9,padding=2)
    ax.set_xticks(x,['Sleeping With Sirens','Archspire','State Champs','Kami Kehoe']);ax.set_ylim(0,110)
    ax.set_ylabel('박20ms F1 (%)');ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True);ax.legend(loc='lower left',fontsize=9)
    ax.set_title('NTM 네 곡: 일부 개선과 큰 회귀·출력 실패가 함께 존재\n참조는 사용자 승인지도 · 박 점수이며 완전한 tempo map 성공률이 아님\nArchspire의 지도 경로 수치는 지도 실패 후 대체 박 출력 점수')
    fig.savefig(root/'ntm-comparison.png',dpi=160);fig.savefig(root/'ntm-comparison.svg');plt.close(fig)
    content=markdown_html((root/'STATUS.md').read_text())
    cards='<div class="cards"><div><b>52</b>음원 예측 보존</div><div><b>38</b>채택 참조 평가</div><div><b>61</b>모델·음원 조합</div><div><b>985</b>특징 자료 보조 평가</div></div>'
    links='<nav><a href="STATUS.md">한국어 원문</a><a href="per-track-method.csv">곡별 CSV</a><a href="summary.json">구조화 결과</a><a href="bar-diagnostics.json">마디 진단</a><a href="region-diagnostics.json">부분 구간</a></nav>'
    figures='<figure><img src="cohort-comparison.png" alt="집단별 박 위치 점수 비교"><figcaption>같은 입력과 고정 설정의 비교. 방법 이름이 비슷해도 처리 경로를 구분했다.</figcaption></figure><figure><img src="ntm-comparison.png" alt="NTM 네 곡의 방법별 박 위치 점수"><figcaption>Archspire의 기존 DBN·마디 독립 점수는 지도 실패 후 대체 박 출력의 점수다. 후보 출력은 비어 있으며, State Champs의 후보 선택 회귀도 포함한다.</figcaption></figure>'
    style='body{font:16px/1.65 system-ui,sans-serif;color:#172033;background:#f5f7fb;margin:0}main{max-width:1180px;margin:auto;padding:30px 24px}h1,h2{line-height:1.3}h2{margin-top:2.5em}nav{display:flex;gap:20px;flex-wrap:wrap}a{color:#155ac9}figure{margin:28px 0;background:white;padding:16px;border-radius:12px}img{width:100%;height:auto}figcaption{font-size:14px;color:#526078}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:24px 0}.cards div{background:white;padding:16px;border-radius:12px}.cards b{display:block;font-size:28px}.table{overflow-x:auto;background:white}table{border-collapse:collapse;min-width:700px;width:100%;font-size:14px}td,th{text-align:left;padding:8px;border-bottom:1px solid #dce3ed}th{background:#e7edf6}p{max-width:1050px}@media(max-width:650px){.cards{grid-template-columns:repeat(2,1fr)}}'
    (root/'index.html').write_text('<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Joljak 현황 재분석</title><style>'+style+'</style><main>'+cards+links+figures+content+'</main></html>')
    print(root/'index.html')

if __name__=='__main__':main()
