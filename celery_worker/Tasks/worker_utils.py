from celery.result import AsyncResult
from celery.states import SUCCESS, FAILURE, RETRY
from db_tables.tables import Document 
from core.Exceptions.exceptions import DocumentNotFoundException
from sqlalchemy import select
from celery_worker.celery_app import celery_app
from utils.APIResponce_error_code_enum import SYSTEM_ERROR_CODES
from utils.schemas import APIResponse, TokenDataSchema
from sqlalchemy.ext.asyncio import AsyncSession



def get_worker_redis_status(task_id: str) -> APIResponse:
    async_result = AsyncResult(task_id, app=celery_app)
    state = async_result.state

    if state == SUCCESS:
        return APIResponse(
            success=True,
            data={
                "status": "completed",
                "task_id": task_id,
                "state": state,
            },
            error_code=None,
            error_message=None,
        )

    elif state == FAILURE:
        return APIResponse(
            success=False,
            data={
                "status": "failed",
                "task_id": task_id,
                "state": state,
                "failed": True,
            },
            error_code=SYSTEM_ERROR_CODES.TASK_FAILED.value,
            error_message=str(async_result.result),
        )

    elif state == RETRY:
        return APIResponse(
            success=True,
            data={
                "status": "retrying",
                "task_id": task_id,
                "state": state,
                "failed": False,
            },
            error_code=None,
            error_message=None,
        )

    else:
        return APIResponse(
            success=True,
            data={
                "status": "processing",
                "task_id": task_id,
                "state": state,
                "failed": False,
            },
            error_code=None,
            error_message=None,
        )





async def get_document_by_request_id(request_id: str, db: AsyncSession, user_jwt_payload: TokenDataSchema) -> dict:
    stmt = select(Document).where(Document.request_id == request_id, Document.user_id == user_jwt_payload.user_id)
    result = await db.execute(stmt)
    document = result.scalar_one_or_none()
    if document is None:
        return {
            "status": "PENDING_SAVE",
            "failure_reason": None,
        }
        
    return {
        "status": document.status,
        "failure_reason": document.failure_reason,
    }

    
def worker_result_handler(result: APIResponse):
    return result.data