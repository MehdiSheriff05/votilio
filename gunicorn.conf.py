import os

bind = "0.0.0.0:8000"
worker_class = "gthread"
workers = int(os.environ.get("WEB_CONCURRENCY", 2))
threads = int(os.environ.get("WEB_THREADS", 4))
timeout = 60
graceful_timeout = 30
keepalive = 5
max_requests = 2000
max_requests_jitter = 200
accesslog = "-"
errorlog = "-"
# The container is only reachable through the compose network / a local reverse proxy.
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "*")
