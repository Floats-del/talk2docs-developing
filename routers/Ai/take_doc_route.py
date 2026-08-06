from fastapi import (
    APIRouter,
    Depends,
    Request,
    Response,
    UploadFile,
    File
)
from core.Exceptions.exceptions import UploadingException
from core.rate_limiters.limiter_file import limiter
from core.rate_limiters.limiter_utils import RateLimits
from Oauth2 import get_user_jwt_payload
from db import get_db
from utils.ai_responce_handler import handle_service_response
from utils.schemas import All_worker_starter_responce, TokenDataSchema, APIResponse, UploadTaskPayload, passed_vlidation_reponce
from sqlalchemy.ext.asyncio import AsyncSession
from Ai.doc_verification_utils import upload_doc_worker_inishiator
from Ai.ai_services import file_validation

router = APIRouter(prefix="/upload", tags=["Upload"])


@router.post("/upload-doc", response_model=All_worker_starter_responce)
@limiter.limit(RateLimits.AI.FILE_UPLOAD) 
async def upload_doc(
    request: Request, response: Response, 
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user_jwt_payload: TokenDataSchema = Depends(get_user_jwt_payload) 
):
    result: APIResponse = await file_validation(file=file, user_jwt_payload=user_jwt_payload)
    data: passed_vlidation_reponce = handle_service_response(result, UploadingException)
    return All_worker_starter_responce(task_id=await upload_doc_worker_inishiator(data=data))
