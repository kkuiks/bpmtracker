"""Small provenance guards for resumable analysis experiments."""
from pathlib import Path
from inspect_inputs import sha256


def source_fingerprint(names):
    root=Path(__file__).parent
    return {name:sha256(root/name) for name in sorted(set(names))}


def require_file_hash(path, expected, label='artifact'):
    path=Path(path)
    if not expected or not path.is_file() or sha256(path)!=expected:
        raise ValueError(label+' missing or changed')
    return path


def prediction_index(manifest):
    """Validate the published prediction ledger before consuming any saved output."""
    result={}
    for row in manifest.get('rows',[]):
        if not row.get('prediction_path'):continue
        key=(row['id'],row['model'])
        if key in result:raise ValueError('duplicate prediction identity in manifest')
        require_file_hash(row['prediction_path'],row.get('prediction_sha256'),'manifest prediction')
        if row.get('candidates_path'):
            require_file_hash(row['candidates_path'],row.get('candidates_sha256'),'candidate pool')
        result[key]=row
    return result


def merge_prediction_rows(current_rows, previous_rows):
    """Keep validated bindings through partial resumes and selective invocations.

    Current status wins. An unvisited or temporarily unselected case retains its
    previous artifact binding, without being claimed as executed in this pass.
    """
    previous={(row['id'],row['model']):dict(row) for row in previous_rows}
    result=[];seen=set()
    for row in current_rows:
        key=(row['id'],row['model'])
        if key in seen:raise ValueError('duplicate current prediction identity')
        seen.add(key);merged=dict(row)
        for field in ('prediction_path','prediction_sha256','candidates_path','candidates_sha256'):
            if field not in merged and field in previous.get(key,{}):merged[field]=previous[key][field]
        result.append(merged)
    result.extend(row for key,row in previous.items() if key not in seen)
    return result
