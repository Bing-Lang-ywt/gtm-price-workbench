"""Export Git object evidence without executing target code or disclosing paths."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_REPLACE_OBJECTS='1', GIT_OPTIONAL_LOCKS='0')
    return subprocess.run(['git', '--no-pager', '-C', str(repo), *args], env=env,
                          check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout


def collect(repo, commit, base, ci_url, result):
    if not all(re.fullmatch('[0-9a-f]{40}', s) for s in (commit, base)):
        raise ValueError('Full commit identifiers required')
    if not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/runs/[0-9]+', ci_url):
        raise ValueError('Invalid validation reference')
    if result not in ('success', 'failure', 'pending'):
        raise ValueError('Invalid reported result')
    for sha in (commit, base):
        if git(repo, 'cat-file', '-t', sha).strip() != b'commit':
            raise ValueError('Commit object required')
    git(repo, 'merge-base', '--is-ancestor', base, commit)
    files = []
    for item in git(repo, 'ls-tree', '-r', '-z', commit).split(b'\0'):
        if not item:
            continue
        meta, path = item.split(b'\t', 1)
        mode, kind, oid = meta.split()
        if kind != b'blob':
            raise ValueError('Submodules are unsupported')
        blob = git(repo, 'cat-file', 'blob', oid.decode())
        files.append({'path_sha256': hashlib.sha256(path).hexdigest(), 'mode': mode.decode(),
                      'size': len(blob), 'content_sha256': hashlib.sha256(blob).hexdigest()})
    canonical = json.dumps(files, sort_keys=True, separators=(',', ':')).encode()
    changed = git(repo, 'diff', '--no-ext-diff', '--no-textconv', '--name-only', '-z', base, commit)
    return {'schema_version': 1, 'commit_sha': commit, 'base_commit_sha': base,
            'tree_sha': git(repo, 'rev-parse', commit + '^{tree}').decode().strip(),
            'source_manifest_sha256': hashlib.sha256(canonical).hexdigest(), 'files': files,
            'change_range': {'from': base, 'to': commit,
                             'changed_path_sha256': [hashlib.sha256(p).hexdigest() for p in changed.split(b'\0') if p]},
            'validation': {'reference': ci_url, 'reported_result': result,
                           'verification': 'caller supplied; not independently verified'},
            'limitations': ['Only committed objects; uncommitted changes excluded.',
                            'Paths hashed; no contents, messages or remote configuration exported.',
                            'Symlink target bytes hashed; links never followed. Submodules refused.',
                            'No target code or tests executed; no network access.',
                            'Checksums do not prove quality, sanitization or platform acceptance.']}


def export(repo, commit, base, output, ci_url, result):
    data = collect(repo, commit, base, ci_url, result)
    with Path(output).open('x', encoding='utf-8') as target:
        json.dump(data, target, ensure_ascii=False, indent=2)
        target.write('\n')
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description='Export fixed-commit evidence')
    parser.add_argument('--repo', type=Path, default=Path('.'))
    for name in ('commit', 'base', 'output', 'ci-url'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--ci-result', choices=['success', 'failure', 'pending'], required=True)
    a = parser.parse_args(argv)
    try:
        export(a.repo, a.commit, a.base, a.output, a.ci_url, a.ci_result)
    except (OSError, ValueError, subprocess.CalledProcessError):
        parser.exit(2, 'Export failed: check fixed commits, ancestry, reference and new output file.\n')
    print('Evidence exported; validation result is caller supplied.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
