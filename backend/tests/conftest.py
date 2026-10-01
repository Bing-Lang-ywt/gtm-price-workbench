"""Keep tests away from local deployments and notifications."""
import os
import tempfile
from pathlib import Path

_TEST_DIR = tempfile.TemporaryDirectory(prefix='gtm-tests-')
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(_TEST_DIR.name) / 'test.db')
os.environ['ENABLE_SCHEDULER'] = '0'
os.environ['ENABLE_SPA_CRAWL'] = '0'
os.environ['SLACK_WEBHOOK_URL'] = ''
os.environ['ALERT_EMAIL_TO'] = ''
os.environ['SMTP_HOST'] = ''
os.environ['MARKET_ACCOUNTS_JSON'] = ''
os.environ['DEV_EMAIL'] = 'analyst@example.com'
os.environ['DEV_PASSWORD'] = 'test-fixture-only-not-a-deployment-password'
os.environ['SECRET_KEY'] = 'test-fixture-only-not-a-deployment-signing-key'

from app.core.db import init_db
init_db()
