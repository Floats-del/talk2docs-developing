from pathlib import Path
from uuid import uuid4
from celery_worker.Tasks.Ai_worker.ai_worker import save_validated_doc_task
from fastapi import UploadFile
from routers.Ai.ai_services import UPLOAD_DIR, ALLOWED_MIME_TYPES
from utils.schemas import TokenDataSchema, passed_vlidation_reponce
import secrets
from utils.schemas import UploadTaskPayload


async def upload_doc_worker_inishiator(data: passed_vlidation_reponce):
    task = save_validated_doc_task.delay(validated_file_data=data.model_dump()) 
    return task.id 