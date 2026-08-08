from celery_worker.Tasks.worker_utils import get_worker_redis_status, get_document_by_request_id, worker_result_handler
from utils.schemas import TokenDataSchema, APIResponse
from sqlalchemy.ext.asyncio import AsyncSession

async def redis_and_db_worker_status(task_id: str, request_id: str, db: AsyncSession, user_jwt_payload: TokenDataSchema) -> APIResponse:
    worker_response: APIResponse = get_worker_redis_status(task_id=task_id)
    document: dict  = await get_document_by_request_id(request_id=request_id, db=db, user_jwt_payload=user_jwt_payload)

    data =  {
        "worker": worker_result_handler(worker_response),
        "document": {
            "status": document["status"],
            "failure_reason": document["failure_reason"],
        },
    }
    return APIResponse(
        success=True,
        data=data,
        error_code=None,
        error_message=None
    )