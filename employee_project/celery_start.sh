# #!/bin/bash
celery -A employee_project worker --queue=image_generation --concurrency=4 --loglevel=info




#! celery -A employee_project worker --queues=image_generation --concurrency=1 --pool=solo --loglevel=info