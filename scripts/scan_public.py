"""Fail on selected private-data and secret patterns; report locations only."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = {
    'home-path': re.compile(r'/(?:Users|home)/[A-Za-z0-9_.-]+'),
    'private-key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'github-token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'),
    'slack-webhook': re.compile(r'https://hooks\.slack\.com/services/[A-Za-z0-9/]+'),
    'credential-url': re.compile(r'https?://[^\s/:]+:[^\s/@]+@'),
}
EMAIL = re.compile(r'\b[\w.+-]+@([\w.-]+\.[A-Za-z]{2,})\b')
ALLOWED_EMAIL_DOMAINS = {'example.com', 'example.org', 'example.net', 'example.invalid'}
FORBIDDEN_SUFFIXES = {'.db', '.sqlite', '.sqlite3', '.xlsx', '.pdf', '.png', '.svg', '.pyc'}


def scan():
    paths = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z']).split(b'\0')
    findings = []
    for raw in paths:
        if not raw:
            continue
        name = raw.decode()
        path = ROOT / name
        if name == 'scripts/scan_public.py':
            continue
        if path.suffix in FORBIDDEN_SUFFIXES or path.name.startswith('._') or (path.name.startswith('.env') and path.name != '.env.example'):
            findings.append((name, 0, 'private-artifact'))
            continue
        try:
            lines = path.read_text().splitlines()
        except UnicodeError:
            findings.append((name, 0, 'unexpected-binary'))
            continue
        for number, line in enumerate(lines, 1):
            for label, pattern in RULES.items():
                if pattern.search(line):
                    findings.append((name, number, label))
            if any(m.group(1).lower() not in ALLOWED_EMAIL_DOMAINS for m in EMAIL.finditer(line)):
                findings.append((name, number, 'non-demo-email'))
    for name, line, label in findings:
        print(f'{name}:{line}: {label}')
    print(f'Public-source scan: {len(findings)} finding(s); heuristic scan, not a security certification')
    return bool(findings)


if __name__ == '__main__':
    raise SystemExit(scan())
