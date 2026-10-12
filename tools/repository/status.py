"""Print current project pointers; never execute pending experiments."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]


def main():
    state = json.loads((ROOT / 'project-state.json').read_text())
    baseline = state['development_baseline']
    app = json.loads((ROOT / 'apps/daw/package.json').read_text())
    print('개발 기준:', baseline['method'], '/', baseline['id'])
    print('개발 진입점:', baseline['entry_point'])
    print('측정된 구현:', baseline['implementation'])
    print('Windows 앱:', app['version'], '(기본 분석기는 고정 전용)')
    print('다음 목표:', state['next_objective']['primary_recording'], '- 세 번 변속·마디 유지')
    print('현재 결과:', baseline['primary_recorded_run'])
    print('직접 청취:', baseline['owner_native_listening'])
    print('안내: docs/DEVELOPMENT.md / docs/CODE_MAP.md / reference/README.md')


if __name__ == '__main__':
    main()
