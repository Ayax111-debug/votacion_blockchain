"""
Celery configuration for votacion_blockchain project.
Handles async task queuing for blockchain operations.
"""

import os
from pathlib import Path
from celery import Celery
from django.conf import settings

# Load .env before anything else
try:
    from dotenv import load_dotenv
    BASE_DIR = Path(__file__).resolve().parent.parent
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'votacion.settings')

app = Celery('votacion')

# Load configuration from Django settings, all config keys should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from all registered Django apps
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
