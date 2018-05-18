celery -A run_server.celery worker &
gunicorn -w 2 --max-requests 50 --threads 1000 -b 0.0.0.0:80 --log-level debug run_server:app
