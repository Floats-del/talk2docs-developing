from fastapi import (
    APIRouter,
    Depends,
    Request,
    Response,
    UploadFile,
    File
)
from routers.Ai.ai_route_utils import redis_and_db_worker_status
from core.Exceptions.exceptions import UploadingException
from core.rate_limiters.limiter_file import limiter
from core.rate_limiters.limiter_utils import RateLimits
from Oauth2 import get_user_jwt_payload
from db import get_db
from utils.ai_responce_handler import handle_service_response
from utils.schemas import All_worker_starter_responce, TokenDataSchema, APIResponse, DataToFrontEndAfterUploadingRoute, passed_vlidation_reponce
from sqlalchemy.ext.asyncio import AsyncSession
from routers.Ai.doc_verification_utils import upload_doc_worker_inishiator
from routers.Ai.ai_services import file_validation_service

router = APIRouter(prefix="/upload", tags=["Upload"])


@router.post("/upload-doc", response_model=All_worker_starter_responce)
@limiter.limit(RateLimits.AI.FILE_UPLOAD) 
async def upload_doc(
    request: Request, response: Response, 
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user_jwt_payload: TokenDataSchema = Depends(get_user_jwt_payload) 
):
    result: APIResponse = await file_validation_service(file=file, user_jwt_payload=user_jwt_payload, db=db)
    data: passed_vlidation_reponce = handle_service_response(result, UploadingException)
    return All_worker_starter_responce(
        task_id=await upload_doc_worker_inishiator(data=data),
        doc_upload_api_responce=DataToFrontEndAfterUploadingRoute(
            request_id=data.file_payload.request_id,
            user_id=user_jwt_payload.user_id
        )
    )


@router.get("/upload_worker/{task_id}/{request_id}")
async def get_upload_worker_result(task_id: str, request_id: str, db: AsyncSession = Depends(get_db), user_jwt_payload: TokenDataSchema = Depends(get_user_jwt_payload)):
    result: APIResponse = await redis_and_db_worker_status(task_id=task_id, request_id=request_id, db=db, user_jwt_payload=user_jwt_payload)
    return result.data
