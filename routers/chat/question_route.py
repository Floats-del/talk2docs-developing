from Ai.Talk2Doc import Answer_ai, AnswerModel
from core.Exceptions.exceptions import NoVectorDatabaseException
from utils.APIResponce_error_code_enum import SYSTEM_ERROR_CODES
from utils.schemas import QuestionRequest
from fastapi import (
    APIRouter,
    Depends,
    Request,
    Response
)
from core.rate_limiters.limiter_file import limiter
from core.rate_limiters.limiter_utils import RateLimits
from Oauth2 import get_user_jwt_payload
from db import get_db
from utils.ai_responce_handler import handle_service_response
from utils.schemas import All_worker_starter_responce, TokenDataSchema, APIResponse, DataToFrontEndAfterUploadingRoute, passed_vlidation_reponce
from sqlalchemy.ext.asyncio import AsyncSession
from vector_db.chroma import get_user_vdb
from langchain_chroma import Chroma
from core.Exceptions.exceptions import AIServiceException
from Ai.main import model 

router = APIRouter(tags=["Question"])




@router.post("/question", response_model=AnswerModel) 
@limiter.limit(RateLimits.AI.ASK_QUESTION) 
async def ask_question(user_payload: QuestionRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db), user_jwt_payload: TokenDataSchema = Depends(get_user_jwt_payload)) -> All_worker_starter_responce:
    user_vdb: Chroma | None = await get_user_vdb(user_id=user_jwt_payload.user_id, db=db)
    if user_vdb is None:
        raise NoVectorDatabaseException(
            error_code=SYSTEM_ERROR_CODES.NO_RELATED_VECTOR_DATABSE_FOUND.value,
            message="Bro typa chat, but aint uploded shit yet man..."
        )
    result: APIResponse = await Answer_ai(model=model, user_id=user_jwt_payload.user_id, user_vdb=user_vdb, user_payload=user_payload, db=db)
    return handle_service_response(result, AIServiceException)
    