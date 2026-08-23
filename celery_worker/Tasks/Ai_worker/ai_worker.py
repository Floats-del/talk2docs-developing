import asyncio
from pathlib import Path
from typing import Any
from celery.result import AsyncResult
import httpx
from langchain_chroma import Chroma
# from celery_worker.tasks.Ai_worker.Ai_worker_utils import get_worker_result
# from celery_worker.tasks.worker_utils import worker_result_handler
from Ai.explain_ai import ExplanationBatchModel, explanation_ai
from Ai.summry_ai import SummaryBatchModel, summry_ai
from core.Exceptions.exceptions import (
ChunkingParsedFileException, 
DocumentNotFoundException, 
EmbeddingChunkedFileException, 
InvalidTask1PayloadException, 
InvalidTask2PayloadException, 
ParsingSavedFileException, 
SavingValidatedFileException, 
TokenizationWorkerStarterException
)
from langchain_core.documents import Document as LangChainDocument
from routers.Ai.ai_services import embedding_model
# from db import AsyncSessionLocal #fastapi db lifecycle
from db import CelerySessionLocal #celery db lifecycle! (celery also has a db session saprate form fastapi!)
from db_tables.tables import Document
from routers.Ai.ai_services import save_validated_doc_task_service, parse_chunk_embed_saved_doc_task2_service
from utils.APIResponce_error_code_enum import SYSTEM_ERROR_CODES, USER_ERROR_CODES
from celery_worker.celery_app import celery_app
from utils.config import settings
from utils.logging.helper_log import log_state
from utils.logging.logEvents import UploadFileLogs
from utils.schemas import  APIResponse, MultiIndexStatus, SavedDocumentPayload, passed_vlidation_reponce
from pydantic import ValidationError


#for task 1:
async def save_validated_doc_task1_async(payload: passed_vlidation_reponce):
    user_id = payload.file_payload.user_id if hasattr(payload, "file_payload") else None
    request_id = payload.file_payload.request_id if hasattr(payload, "file_payload") else None
    
    log_state(UploadFileLogs.SAVE_TASK1_ASYNC_STARTED, function="save_validated_doc_task1_async", user_id=user_id, request_id=request_id)
    
    async with CelerySessionLocal() as db:       
        result: dict = await save_validated_doc_task_service(
            payload=payload,
            db=db
        )
        
    log_state(UploadFileLogs.SAVE_TASK1_ASYNC_SUCCESS, function="save_validated_doc_task1_async", user_id=user_id, request_id=request_id)
    return result


#task 2:
async def parse_chunk_embed_saved_doc_task2_async(doc_meta_obj: SavedDocumentPayload):
    log_state(UploadFileLogs.TASK_2_ASYNC_STARTED, function="parse_chunk_embed_saved_doc_task2_async", user_id=doc_meta_obj.user_id, request_id=doc_meta_obj.request_id)
    
    async with CelerySessionLocal() as db:        
        await parse_chunk_embed_saved_doc_task2_service( 
            doc_meta_obj=doc_meta_obj,
            db=db
        )
    log_state(UploadFileLogs.TASK_2_ASYNC_SUCCESS, function="parse_chunk_embed_saved_doc_task2_async", user_id=doc_meta_obj.user_id, request_id=doc_meta_obj.request_id)



# celery of task2 
@celery_app.task(bind=True, max_retries=3, name="ai.parse_doc_worker") 
def parse_chunk_embed_saved_doc_task2_inishiator(self, doc_meta_dict: dict):
    user_id = doc_meta_dict.get("user_id")
    request_id = doc_meta_dict.get("request_id")
    
    log_state(UploadFileLogs.TASK_2_STARTED, function="parse_chunk_embed_saved_doc_task2_inishiator", user_id=user_id, request_id=request_id)
    
    try: 
        log_state(UploadFileLogs.VALIDATING_TASK_2_PAYLOAD, function="parse_chunk_embed_saved_doc_task2_inishiator", user_id=user_id, request_id=request_id)
        doc_meta_obj = SavedDocumentPayload.model_validate(doc_meta_dict)
        
        log_state(UploadFileLogs.RUNNING_TASK_2_ASYNC, function="parse_chunk_embed_saved_doc_task2_inishiator", user_id=user_id, request_id=request_id)
        asyncio.run( 
            parse_chunk_embed_saved_doc_task2_async(
                doc_meta_obj
            )
        )
        log_state(UploadFileLogs.TASK_2_SUCCESS, function="parse_chunk_embed_saved_doc_task2_inishiator", user_id=user_id, request_id=request_id)
        
    except ValidationError as exc:
        log_state(UploadFileLogs.TASK_2_VALIDATION_ERROR, function="parse_chunk_embed_saved_doc_task2_inishiator", user_id=user_id, request_id=request_id)
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
        log_state(UploadFileLogs.TASK_2_RETRYING, function="parse_chunk_embed_saved_doc_task2_inishiator", user_id=user_id, request_id=request_id, exc=exc)
        raise self.retry(exc=exc, countdown=1)





@celery_app.task(bind=True, max_retries=3, name="ai.upload_save_file_worker") 
def save_validated_doc_task(self, validated_file_data: dict):
    user_id = validated_file_data.get("file_payload", {}).get("user_id")
    request_id = validated_file_data.get("file_payload", {}).get("request_id")
    log_state(UploadFileLogs.SAVE_TASK_STARTED, function="save_validated_doc_task", user_id=user_id, request_id=request_id)
    
    try:  
        log_state(UploadFileLogs.VALIDATING_TASK_PAYLOAD, function="save_validated_doc_task", user_id=user_id, request_id=request_id)
        payload: passed_vlidation_reponce = passed_vlidation_reponce.model_validate(validated_file_data)  # here we go we made it object again!
        
        log_state(UploadFileLogs.SAVING_DOC_TO_DB, function="save_validated_doc_task", user_id=user_id, request_id=request_id)
        doc_meta_dict: dict = asyncio.run( 
            save_validated_doc_task1_async(
                payload
            )
        )
        
        try:
            log_state(UploadFileLogs.INITIATING_TASK_2, function="save_validated_doc_task", user_id=user_id, request_id=request_id)
            result: AsyncResult = parse_chunk_embed_saved_doc_task2_inishiator.delay(doc_meta_dict) 
            log_state(UploadFileLogs.TASK_2_INITIATED_SUCCESS, function="save_validated_doc_task", user_id=user_id, request_id=request_id)
            
        except Exception as e:
            log_state(UploadFileLogs.TASK_2_INITIATION_FAILED, function="save_validated_doc_task", user_id=user_id, request_id=request_id)
            raise TokenizationWorkerStarterException(
                error_code=SYSTEM_ERROR_CODES.TOKENIZATION_EXCEPTION.value,
                message="Task 2 inishiator failed, thus parsing, chunking, embeding didnt start"
            ) from e 
        
    except ValidationError as exc:
        log_state(UploadFileLogs.TASK_VALIDATION_ERROR, function="save_validated_doc_task", user_id=user_id, request_id=request_id)
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
        log_state(UploadFileLogs.TASK_RETRYING, function="save_validated_doc_task", user_id=user_id, request_id=request_id, exc=exc)
        raise self.retry(exc=exc, countdown=1)




@celery_app.task(bind=True, max_retries=3, name="ai.create_rest_vdbs")
def multi_index_db_creation_task(self, doc_id: int, create_summary: bool, create_explanation: bool, user_id: int) -> dict[str, Any]:
    """Synchronous Celery entrypoint managing the event loop lifecycle."""
    log_state(UploadFileLogs.MULTI_INDEX_TASK_STARTED, function="multi_index_db_creation_task", user_id=user_id)
    try:
        return asyncio.run(
            multi_index_db_creation_async(
                task_instance=self, 
                doc_id=doc_id,
                create_summary=create_summary,
                create_explanation=create_explanation,
                user_id=user_id,
            )
        )
    except Exception as exc:
        # Fallback task retry if an unhandled exception bubbles out
        raise self.retry(exc=exc, countdown=10)




async def multi_index_db_creation_async(task_instance: Any, doc_id: int, create_summary: bool, create_explanation: bool, user_id: int) -> dict[str, Any]:
    log_state(UploadFileLogs.FETCHING_DOCUMENT_FOR_TASK, function="multi_index_db_creation_async", user_id=user_id, request_id=str(doc_id))
    
    async with CelerySessionLocal() as db:
        document = await db.get(Document, doc_id)
        if document is None:
            log_state(UploadFileLogs.UPLOAD_FAILED, function="multi_index_db_creation_async", user_id=user_id, request_id=str(doc_id))
            raise DocumentNotFoundException(
                error_code=SYSTEM_ERROR_CODES.DOCUMENT_NOT_FOUND.value,
                message="Document not found for multi-index VDB creation.",
            )
    
        collection_name = document.collection_name
        summary_status = document.summary_vdb_status
        explanation_status = document.explanation_vdb_status

    user_chroma_dir = Path(settings.chroma_db_dir) / f"user_{user_id}"

    
    
    
    log_state(UploadFileLogs.FETCHING_RAW_CHUNKS, function="multi_index_db_creation_async", user_id=user_id)
    primary_vdb = Chroma(
        collection_name=collection_name,
        persist_directory=str(user_chroma_dir),
        embedding_function=embedding_model,
    ) 

    raw_data = await asyncio.to_thread(
        primary_vdb.get, 
        where={"doc_id": doc_id},
    )

    raw_texts: list[str] = raw_data.get("documents", []) 
    raw_metadatas: list[dict] = raw_data.get("metadatas", [])

    if not raw_texts:
        return {
            "success": False,
            "doc_id": doc_id,
            "message": f"No raw chunks found in Chroma for doc_id: {doc_id}",
        }

    final_summary_status = summary_status
    final_explanation_status = explanation_status


    if create_summary and summary_status != MultiIndexStatus.READY:
        log_state(UploadFileLogs.BUILDING_SUMMARY_VDB, function="multi_index_db_creation_async", user_id=user_id)
        try:
            summary_response: APIResponse = await summry_ai(raw_texts, user_id)
            if summary_response.success:
                summary_batch: SummaryBatchModel = summary_response.data
                
                summary_docs = [
                    LangChainDocument(
                        page_content=summary.text,
                        metadata={
                            **meta, 
                            "doc_type": "summary",
                            "raw_content": raw_text, 
                        },
                    )
                    for raw_text, meta, summary in zip(
                        raw_texts,
                        raw_metadatas,
                        summary_batch.summaries,
                    )
                ] 

                await asyncio.to_thread(
                    Chroma.from_documents,
                    documents=summary_docs,
                    embedding=embedding_model,
                    collection_name=f"{collection_name}_summary",
                    persist_directory=str(user_chroma_dir),
                )

                final_summary_status = MultiIndexStatus.READY
                log_state(UploadFileLogs.SUMMARY_VDB_SUCCESS, function="multi_index_db_creation_async", user_id=user_id)

            else:
                final_summary_status = MultiIndexStatus.FAILED
                log_state(UploadFileLogs.SUMMARY_VDB_FAILED, function="multi_index_db_creation_async", user_id=user_id)

        except Exception as exc:
            print(f"[SUMMARY VDB FAILED] {type(exc).__name__}: {exc}", flush=True)
            final_summary_status = MultiIndexStatus.FAILED
            log_state(UploadFileLogs.SUMMARY_VDB_FAILED, function="multi_index_db_creation_async", user_id=user_id)

    # EXPLANATION INDEX
    if create_explanation and explanation_status != MultiIndexStatus.READY:
        log_state(UploadFileLogs.BUILDING_EXPLANATION_VDB, function="multi_index_db_creation_async", user_id=user_id)
        try:
            explanation_response: APIResponse = await explanation_ai(raw_texts, user_id)

            if explanation_response.success:
                explanation_batch: ExplanationBatchModel = explanation_response.data

                explanation_docs = [
                    LangChainDocument(
                        page_content=item.explanation,
                        metadata={
                            **meta,  # Original metadata from initial VDB
                            "doc_type": "explanation",
                            "raw_content": raw_text,  # Raw chunk preserved in metadata
                            "topic": item.topic,      # Extra filterable metadata if available
                            "key_takeaway": item.key_takeaway,
                        },
                    )
                    for raw_text, meta, item in zip(
                        raw_texts,
                        raw_metadatas,
                        explanation_batch.explanations,
                    )
                ]

                await asyncio.to_thread(
                    Chroma.from_documents,
                    documents=explanation_docs,
                    embedding=embedding_model,
                    collection_name=f"{collection_name}_explanation",
                    persist_directory=str(user_chroma_dir),
                )

                final_explanation_status = MultiIndexStatus.READY
                log_state(UploadFileLogs.EXPLANATION_VDB_SUCCESS, function="multi_index_db_creation_async", user_id=user_id)
            else:
                final_explanation_status = MultiIndexStatus.FAILED
                log_state(UploadFileLogs.EXPLANATION_VDB_FAILED, function="multi_index_db_creation_async", user_id=user_id)

        except Exception as exc:
            print(f"[explain VDB FAILED] {type(exc).__name__}: {exc}", flush=True)
            final_explanation_status = MultiIndexStatus.FAILED
            log_state(UploadFileLogs.EXPLANATION_VDB_FAILED, function="multi_index_db_creation_async", user_id=user_id)

    # --- SESSION 2: Open a fresh, short-lived session just to commit the statuses ---
    async with CelerySessionLocal() as db:
        document = await db.get(Document, doc_id)
        if document:
            document.summary_vdb_status = final_summary_status
            document.explanation_vdb_status = final_explanation_status
            await db.commit()

    log_state(UploadFileLogs.MULTI_INDEX_TASK_COMPLETED, function="multi_index_db_creation_async", user_id=user_id)

    return {
        "success": True,
        "doc_id": doc_id,
        "summary_status": final_summary_status.value,
        "explanation_status": final_explanation_status.value,
    }