from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from celery_worker.Tasks.Ai_worker.ai_worker import save_validated_doc_task, multi_index_db_creation_task
from fastapi import UploadFile
from db_tables.tables import Document
from routers.Ai.ai_services import UPLOAD_DIR, ALLOWED_MIME_TYPES
from utils.APIResponce_error_code_enum import SYSTEM_ERROR_CODES
from utils.schemas import APIResponse, DocumentStatus, MultiIndexStatus, TokenDataSchema, passed_vlidation_reponce
import secrets
from utils.schemas import UploadTaskPayload

from sqlalchemy.ext.asyncio import AsyncSession

async def upload_doc_worker_inishiator(data: passed_vlidation_reponce):
    task = save_validated_doc_task.delay(validated_file_data=data.model_dump())  
    return task.id 



async def multi_index_db_creation_worker_inishiator(user_id: int, request_id: str, db: AsyncSession) -> APIResponse:

    
    stmt = select(Document).where(
        Document.request_id == request_id,
        Document.user_id == user_id,
    )

    result = await db.execute(stmt)
    document = result.scalar_one_or_none()

    
    if document is None:
        return APIResponse(
            success=False,
            data=None,
            error_code=SYSTEM_ERROR_CODES.DOCUMENT_NOT_FOUND.value,
            error_message="Document not found for multi-index creation.",
        )

    if document.status != DocumentStatus.READY:
        return APIResponse(
            success=False,
            data=None,
            error_code=None,
            error_message=None,
        ) 


    if (
        document.summary_vdb_status == MultiIndexStatus.READY
        and document.explanation_vdb_status == MultiIndexStatus.READY
    ):
        return APIResponse(
            success=False,
            data=None,
            error_code=None,
            error_message=None,
        ) 

    
    
    create_summary = document.summary_vdb_status in (
        MultiIndexStatus.PENDING,
        MultiIndexStatus.FAILED,
    )

    create_explanation = document.explanation_vdb_status in (
        MultiIndexStatus.PENDING,
        MultiIndexStatus.FAILED,
    )

    
    
    if (
        document.summary_vdb_status == MultiIndexStatus.PROCESSING
        or document.explanation_vdb_status == MultiIndexStatus.PROCESSING
    ):
        return APIResponse(
            success=False,
            data=None,
            error_code=None,
            error_message=None,
        ) 

    
    if not create_summary and not create_explanation:
        return APIResponse(
            success=False,
            data=None,
            error_code=None,
            error_message=None,
        )

    
    
    if create_summary:
        document.summary_vdb_status = MultiIndexStatus.PROCESSING

    if create_explanation:
        document.explanation_vdb_status = MultiIndexStatus.PROCESSING

    await db.commit()


    
    task = multi_index_db_creation_task.delay(
        document.doc_id,
        create_summary,
        create_explanation,
        user_id
    )

    return APIResponse(
        success=True,
        data={
            "doc_id": document.doc_id,
            "create_summary": create_summary,
            "create_explanation": create_explanation,
            "task_id": task.id,
        },
        error_code=None,
        error_message=None,
    )
    
    