import asyncio
from multiprocessing.pool import AsyncResult
import httpx
# from celery_worker.tasks.Ai_worker.Ai_worker_utils import get_worker_result
# from celery_worker.tasks.worker_utils import worker_result_handler
from core.Exceptions.exceptions import AIServiceException, UploadingException
from db import AsyncSessionLocal
from db_tables.tables import Document
from routers.Ai.ai_services import save_validated_doc_task_service, parse_chunk_embed_saved_doc_task2_service
from utils.APIResponce_error_code_enum import SYSTEM_ERROR_CODES, USER_ERROR_CODES
from utils.ai_responce_handler import is_system_failure
from celery_worker.celery_app import celery_app
from utils.schemas import APIResponse, ParsedDocumentPayload, RephraseOutput_route, SavedDocumentPayload, SentimentAnalysisOut_route, SummaryOut_route, Title_genOut_Route, UploadTaskPayload, passed_vlidation_reponce
from routers.Ai import router
from fastapi import UploadFile
import json


#for task 1:
async def save_validated_doc_task1_async(payload: passed_vlidation_reponce):
    async with AsyncSessionLocal() as db:       
        success = False
        result: dict = await save_validated_doc_task_service(
            payload=payload,
            db=db
        )
        success = not is_system_failure(result)
        return result
    #noo need to try and except because save_validated_doc_task_service already does that


#task 2:
async def parse_chunk_embed_saved_doc_task2_async(doc_meta_obj: SavedDocumentPayload):
    async with AsyncSessionLocal() as db:
        await parse_chunk_embed_saved_doc_task2_service( #done, no need to return since task2_parse_saved_doc_service will run and our game is played!
            doc_meta_obj=doc_meta_obj,
            db=db
        )


#celery of task2 
@celery_app.task(bind=True, max_retries=3, name="ai.parse_doc_worker") 
def parse_chunk_embed_saved_doc_task2_inishiator(self, doc_meta_dict: dict):
    try: #see this looks similar to how the first ever celery looked ;)
        doc_meta_obj = SavedDocumentPayload.model_validate(doc_meta_dict)
        asyncio.run( 
            parse_chunk_embed_saved_doc_task2_async(
                doc_meta_obj
            )
        )
        
        #now we can use doc_meta_obj for task 3 ;) [but we dont need now] we couldved called another @celery_app.task() def task3_inishiator which will have task which calls asycn task which calls service yk how it goes
        
        
    except UploadingException as exc: #change this Exception to whatever task2_parse_saved_doc_service throws
        if exc.error_code == SYSTEM_ERROR_CODES.FILE_UPLOAD_EXCEPTION.value:
            raise self.retry(exc=exc, countdown=1)
    except (
        httpx.TimeoutException,
        ConnectionError,
    ) as exc:
        raise self.retry(exc=exc, countdown=1)





#celery of task 1
@celery_app.task(bind=True, max_retries=3, name="ai.upload_save_file_worker") 
def save_validated_doc_task(self, validated_file_data: dict):
    #why do i say dict? well celery works best with not objects so... coz ive to send dict to here via .dely() which no like object lol
    try:
        #task_1 -> saving validated doc dir and its id to db
        payload: passed_vlidation_reponce = passed_vlidation_reponce.model_validate(validated_file_data) #here we go we made it object again!
        doc_meta_dict: dict = asyncio.run( 
            save_validated_doc_task1_async(
                payload
            )
        )
        
        #task_2 -> docling -> chunk -> embed
        result: AsyncResult = parse_chunk_embed_saved_doc_task2_inishiator.delay(doc_meta_dict) #this dely wont have task_id, coz all worker chain are tited to first task_id
        #AsyncResult is basically asyncio obj, if we do result.get() then! we will get task2_parse_saved_doc's return dict which is ParsedDocumentPayload
        #but the work here is done! of this celery! lets go to: task2_parse_saved_doc -> it will have dict that we will send to task3
        
    except UploadingException as exc:
        if exc.error_code == SYSTEM_ERROR_CODES.FILE_UPLOAD_EXCEPTION.value: #well coz all other excpetions are user caused, since this is system caused it deserves a retry
            raise self.retry(exc=exc, countdown=1)

    except (
        httpx.TimeoutException,
        ConnectionError,
    ) as exc:
        raise self.retry(exc=exc, countdown=1)