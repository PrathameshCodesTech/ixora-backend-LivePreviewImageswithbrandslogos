#!/bin/bash
celery -A employee_project worker --queue=image_generation --concurrency=4 --loglevel=info