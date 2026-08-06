from celery import Celery

celery_app = Celery(
    "fastapi_ai_backend",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/1",
)

celery_app.conf.imports = (
    "celery_worker.tasks.Ai_worker"
)



celery_app.conf.task_default_queue = "default"
celery_app.conf.task_routes = {
    "ai.*": { 
        "queue": "ai"
    },
    "email.*": {
        "queue": "email"
    },
    "maintenance.*": {
        "queue": "maintenance"
    },
}