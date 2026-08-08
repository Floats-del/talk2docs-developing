import asyncio
from celery.result import AsyncResult
import httpx
from core.Exceptions.exceptions import (
ChunkingParsedFileException, 
EmbeddingChunkedFileException, 
InvalidTask1PayloadException, 
InvalidTask2PayloadException, 
ParsingSavedFileException, 
SavingValidatedFileException, 
TokenizationWorkerStarterException
)

from db import AsyncSessionLocal
from routers.Ai.ai_services import save_validated_doc_task_service, parse_chunk_embed_saved_doc_task2_service
from utils.APIResponce_error_code_enum import SYSTEM_ERROR_CODES, USER_ERROR_CODES
from celery_worker.celery_app import celery_app
from utils.schemas import  SavedDocumentPayload, passed_vlidation_reponce
from pydantic import ValidationError




#for task 1:
async def save_validated_doc_task1_async(payload: passed_vlidation_reponce):
    async with AsyncSessionLocal() as db:       
        result: dict = await save_validated_doc_task_service(
            payload=payload,
            db=db
        )
        return result


#task 2:
async def parse_chunk_embed_saved_doc_task2_async(doc_meta_obj: SavedDocumentPayload):
    async with AsyncSessionLocal() as db:
        await parse_chunk_embed_saved_doc_task2_service( 
            doc_meta_obj=doc_meta_obj,
            db=db
        )



#celery of task2 
@celery_app.task(bind=True, max_retries=3, name="ai.parse_doc_worker") 
def parse_chunk_embed_saved_doc_task2_inishiator(self, doc_meta_dict: dict):
    try: 
        doc_meta_obj = SavedDocumentPayload.model_validate(doc_meta_dict)
        asyncio.run( 
            parse_chunk_embed_saved_doc_task2_async(
                doc_meta_obj
            )
        )

    except ValidationError as exc:
        raise InvalidTask2PayloadException(
            error_code=SYSTEM_ERROR_CODES.INVALID_TASK2_PAYLOAD.value,
            message="The file_validation worker failed b4 asyc wrapper"
        ) from exc
        
        
    except (
        httpx.TimeoutException,
        ConnectionError,
        ParsingSavedFileException,
        ChunkingParsedFileException,
        EmbeddingChunkedFileException,
    ) as exc:
        raise self.retry(exc=exc, countdown=1)





#celery of task 1
@celery_app.task(bind=True, max_retries=3, name="ai.upload_save_file_worker") 
def save_validated_doc_task(self, validated_file_data: dict):
    try:
        payload: passed_vlidation_reponce = passed_vlidation_reponce.model_validate(validated_file_data) 
        doc_meta_dict: dict = asyncio.run( 
            save_validated_doc_task1_async(
                payload
            )
        )
        
        try:
            result: AsyncResult = parse_chunk_embed_saved_doc_task2_inishiator.delay(doc_meta_dict) 
        except Exception as e:
            raise TokenizationWorkerStarterException(
                error_code=SYSTEM_ERROR_CODES.TOKENIZATION_EXCEPTION.value,
                message="Task 2 inishiator failed, thus parsing, chunking, embeding didnt start"
            ) from e 
        
    except ValidationError as exc:
        raise InvalidTask1PayloadException( 
            error_code=SYSTEM_ERROR_CODES.INVALID_TASK1_PAYLOAD.value,
            message="The worker received an invalid payload before entering the async wrapper, due to not getting proper pydantic obj->dict"
        ) from exc
        
        
    except (
        httpx.TimeoutException,
        ConnectionError,
        SavingValidatedFileException,
        TokenizationWorkerStarterException, 
    ) as exc:
        raise self.retry(exc=exc, countdown=1)