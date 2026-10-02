import hashlib
import json
import subprocess
import pytest
from app.commit_evidence import collect, export, main
URL = 'https://github.com/demo/repo/actions/runs/123'


def run(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args]).decode().strip()


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    run(repo, 'init', '-q')
    run(repo, 'config', 'user.name', 'Demo')
    run(repo, 'config', 'user.email', 'demo@example.com')
    (repo / 'sample.txt').write_text('first')
    run(repo, 'add', '.')
    run(repo, 'commit', '-qm', 'base')
    base = run(repo, 'rev-parse', 'HEAD')
    (repo / 'sample.txt').write_text('second')
    (repo / 'danger.py').write_text("raise RuntimeError('must not execute')")
    run(repo, 'add', '.')
    run(repo, 'commit', '-qm', 'next')
    return repo, base, run(repo, 'rev-parse', 'HEAD')


def test_fixed_objects(repository):
    repo, base, head = repository
    before = collect(repo, head, base, URL, 'success')
    (repo / 'sample.txt').write_text('uncommitted secret')
    (repo / 'untracked').write_text('private')
    assert collect(repo, head, base, URL, 'success') == before
    text = json.dumps(before)
    assert str(repo) not in text and 'secret' not in text and 'sample.txt' not in text
    assert len(before['files']) == 2
    assert len(before['change_range']['changed_path_sha256']) == 2
    assert hashlib.sha256(b'second').hexdigest() in text


def test_exclusive_export(repository, tmp_path):
    repo, base, head = repository
    output = tmp_path / 'evidence.json'
    export(repo, head, base, output, URL, 'pending')
    saved = output.read_bytes()
    with pytest.raises(FileExistsError):
        export(repo, head, base, output, URL, 'success')
    link = tmp_path / 'link.json'
    link.symlink_to(output)
    with pytest.raises(FileExistsError):
        export(repo, head, base, link, URL, 'success')
    assert output.read_bytes() == saved


@pytest.mark.parametrize('kind', ['short', 'reversed', 'credential_url'])
def test_invalid_inputs(repository, kind):
    repo, base, head = repository
    if kind == 'short':
        head = head[:7]
    if kind == 'reversed':
        base, head = head, base
    url = URL if kind != 'credential_url' else 'https://' + 'user:password' + '@example.com'
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        collect(repo, head, base, url, 'success')


def test_cli_error_hides_paths(tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        main(['--repo', str(tmp_path), '--commit', 'bad', '--base', 'bad',
              '--output', str(tmp_path / 'out'), '--ci-url', URL, '--ci-result', 'failure'])
    assert error.value.code == 2
    assert str(tmp_path) not in capsys.readouterr().err
