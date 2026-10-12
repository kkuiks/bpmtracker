"""Owner-invoked static repository inventory; no model or runtime execution."""
from __future__ import annotations
import argparse
import ast
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
OWNED = {'algorithms', 'apps', 'docs', 'experiments', 'reference', 'tools'}
GENERATED = {'node_modules', 'dist', '__pycache__', 'out'}


def read(path):
    return json.loads(Path(path).read_text())


def owned(path):
    rel = path.relative_to(ROOT)
    return (len(rel.parts) == 1 or rel.parts[0] in OWNED) and not GENERATED.intersection(rel.parts)


def metadata(excluded):
    rows, links, errors = [], [], []
    pending = [ROOT]
    while pending:
        folder = pending.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError as error:
            errors.append({'path': str(folder), 'error': str(error)})
            continue
        for entry in entries:
            path = Path(entry.path)
            if any(path == x or x in path.parents for x in excluded):
                continue
            try:
                if entry.is_symlink():
                    links.append({'path': str(path.relative_to(ROOT)), 'target': os.readlink(path)})
                elif entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    rows.append({'path': str(path.relative_to(ROOT)), 'bytes': entry.stat(follow_symlinks=False).st_size})
            except OSError as error:
                errors.append({'path': str(path), 'error': str(error)})
    return rows, links, errors


def python_layout(files):
    reference = set(read(ROOT / 'reference/catalog.json')['experimental_packages'])
    modules = {}
    for path in files:
        if path.suffix != '.py':
            continue
        parts = list(path.relative_to(ROOT).with_suffix('').parts)
        if parts[-1] == '__init__':
            parts.pop()
        names = ['.'.join(parts)]
        if len(parts) > 1 and parts[0] == 'reference' and parts[1] in reference:
            names.append('.'.join(['experiments', *parts[1:]]))
        for name in names:
            modules[name] = path
    known = set(modules)
    for name in modules:
        parts = name.split('.')
        known.update('.'.join(parts[:i]) for i in range(1, len(parts)))
    syntax_errors, missing = [], []
    for name, path in modules.items():
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError as error:
            syntax_errors.append({'path': str(path.relative_to(ROOT)), 'error': str(error)})
            continue
        package = name.split('.') if path.name == '__init__.py' else name.split('.')[:-1]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                prefix = '.'.join(package[:len(package) - node.level + 1]) if node.level else ''
                targets = ['.'.join(x for x in [prefix, node.module or ''] if x)]
            else:
                continue
            for target in targets:
                if target.split('.')[0] in {'algorithms', 'experiments', 'reference', 'tools'} and target not in known:
                    missing.append({'path': str(path.relative_to(ROOT)), 'line': node.lineno, 'module': target})
    return {'files': len({str(p) for p in modules.values()}), 'syntax_errors': syntax_errors,
            'unresolved_owned_imports': missing}


def script_layout(files):
    failures, count = [], 0
    pattern = re.compile(r'(?:\bfrom\s*|\bimport\s*|\brequire\s*\(\s*)[\'\"](\.[^\'\"]+)[\'\"]')
    for path in files:
        if path.suffix not in {'.ts', '.tsx', '.js', '.mjs', '.cjs'}:
            continue
        for match in pattern.finditer(path.read_text()):
            count += 1
            target = path.parent / match.group(1)
            candidates = [target] + [Path(str(target) + suffix) for suffix in ['.ts', '.tsx', '.js', '.mjs', '.cjs', '.css', '.json']]
            candidates += [target / ('index' + suffix) for suffix in ['.ts', '.tsx', '.js', '.mjs', '.cjs']]
            if not any(p.is_file() for p in candidates):
                failures.append({'path': str(path.relative_to(ROOT)), 'target': match.group(1)})
    return {'relative_imports_checked': count, 'unresolved_relative_imports': failures}


def document_layout(files):
    missing, checked = [], 0
    pattern = re.compile(r'\]\((<[^>]+>|[^\s)]+)(?:\s+"[^"\n]*")?\)')
    for path in files:
        if path.suffix != '.md':
            continue
        for match in pattern.finditer(path.read_text()):
            token = match.group(1).strip('<>')
            url = urlsplit(token)
            if url.scheme or url.netloc or not url.path:
                continue
            target = Path(unquote(url.path))
            if not target.is_absolute():
                target = path.parent / target
            checked += 1
            if not target.exists():
                missing.append({'document': str(path.relative_to(ROOT)), 'target': token})
    return {'local_links_checked': checked, 'missing_local_links': missing}


def frozen_layout(state):
    baseline = state['development_baseline']
    results = []
    for key in ['primary_recorded_run', 'broader_fixed_verification']:
        run = ROOT / baseline[key]
        freeze = read(run / 'freeze.json')
        missing, changed = [], []
        for relative, expected in freeze['code_hashes'].items():
            path = ROOT / relative
            if not path.is_file():
                missing.append(relative)
            elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                changed.append(relative)
        results.append({'run': baseline[key], 'source_files': len(freeze['code_hashes']),
                        'missing': missing, 'changed': changed})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exclude', type=Path, action='append', default=[])
    args = parser.parse_args()
    output = args.output.resolve()
    if ROOT not in output.parents:
        raise ValueError('Keep audit artifacts inside this checkout')
    output.mkdir(parents=True, exist_ok=False)
    excluded = [output, *[p.resolve() for p in args.exclude]]
    rows, links, errors = metadata(excluded)
    files = [ROOT / row['path'] for row in rows if owned(ROOT / row['path'])]
    groups = defaultdict(lambda: {'files': 0, 'bytes': 0})
    for row in rows:
        group = groups[row['path'].split('/')[0]]
        group['files'] += 1
        group['bytes'] += row['bytes']
    state = read(ROOT / 'project-state.json')
    python = python_layout(files)
    scripts = script_layout(files)
    documents = document_layout(files)
    frozen = frozen_layout(state)
    index = subprocess.check_output(['git', 'ls-files', '--stage', '-z'], cwd=ROOT)
    report = {'at_utc': datetime.now(timezone.utc).isoformat(), 'files': len(rows),
        'bytes': sum(r['bytes'] for r in rows), 'by_top_level': dict(sorted(groups.items())),
        'symlinks_not_followed': links, 'metadata_errors': errors,
        'owned_source_files': len(files), 'python': python, 'scripts': scripts,
        'documents': documents, 'frozen_baseline_sources': frozen,
        'owner_index_entries_sha256': hashlib.sha256(index).hexdigest(),
        'no_media_decoding_or_hashing': True, 'no_runtime_tests_or_model_runs': True,
        'no_git_mutations_or_cleanup': True}
    report['all_pass'] = not (errors or python['syntax_errors'] or python['unresolved_owned_imports']
        or scripts['unresolved_relative_imports'] or documents['missing_local_links']
        or any(r['missing'] or r['changed'] for r in frozen))
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    (output / 'files.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')
    print('STATIC_REPOSITORY_AUDIT', len(rows), 'FILES', len(files), 'OWNED SOURCE FILES',
          'PASS' if report['all_pass'] else 'REVIEW FINDINGS', flush=True)
    print('Python:', python['files'], 'syntax', len(python['syntax_errors']),
          'owned imports', len(python['unresolved_owned_imports']))
    print('Script imports:', scripts['relative_imports_checked'], 'missing', len(scripts['unresolved_relative_imports']))
    print('Markdown links:', documents['local_links_checked'], 'missing', len(documents['missing_local_links']))
    print('Frozen baseline:', [(r['source_files'], len(r['changed']), len(r['missing'])) for r in frozen])


if __name__ == '__main__':
    main()
