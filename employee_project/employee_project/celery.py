import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'employee_project.settings_local')

app = Celery('employee_project')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
