# #!/bin/bash

# # Kill existing workers
# pkill -f 'celery worker'

# # Start multiple workers with different concurrency levels
# echo "Starting Celery workers..."

# # High priority worker for small tasks
# celery -A employee_project worker \
#     --hostname=worker1@%h \
#     --queues=default \
#     --concurrency=2 \
#     --max-tasks-per-child=100 \
#     --loglevel=info &

# # Image generation workers (memory intensive)
# celery -A employee_project worker \
#     --hostname=worker2@%h \
#     --queues=image_generation \
#     --concurrency=4 \
#     --max-tasks-per-child=25 \
#     --pool=prefork \
#     --loglevel=info &

# # Backup worker with autoscaling
# celery -A employee_project worker \
#     --hostname=worker3@%h \
#     --queues=image_generation,default \
#     --autoscale=4,1 \
#     --max-tasks-per-child=50 \
#     --loglevel=info &

# echo "Workers started. Run 'celery -A employee_project status' to check status"