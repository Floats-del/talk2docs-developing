from pathlib import Path
from uuid import uuid4
from fastapi import UploadFile
import filetype
import secrets
from core.Exceptions.exceptions import UploadingException
from db_tables.tables import Document
from utils.APIResponce_error_code_enum import SYSTEM_ERROR_CODES, USER_ERROR_CODES
from utils.config import Settings
from docling.document_converter import DocumentConverter
from utils.schemas import DocumentStatus, ParsedDocumentPayload, SavedDocumentPayload, TokenDataSchema, UploadTaskPayload, APIResponse, passed_vlidation_reponce
from sqlalchemy.ext.asyncio import AsyncSession
from docling.chunking import HybridChunker
from transformers import AutoTokenizer
from langchain_core.documents import Document as LangChainDocument #coz ive Document as a db table dont want no mixing
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings


model_id = Settings.tokenizer
tokenizer_ = AutoTokenizer.from_pretrained(model_id)
embedding_model = HuggingFaceEmbeddings(
    model_name=Settings.embedding_model
)


UPLOAD_DIR = Settings.upload_dir
UPLOAD_DIR.mkdir(exist_ok=True, parents=True)
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB
ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".txt",
    ".md",
}

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "text/markdown",
}

DEFAULT_COLLECTION_NAME = "talk2docs"

async def file_validation(file: UploadFile, user_jwt_payload: TokenDataSchema) -> APIResponse:
    request_id = str(uuid4())
    user_id = user_jwt_payload.user_id
    
    file_extension = str(Path(file.filename).suffix.lower())
    original_filename = file.filename
    stored_filename = f"{secrets.token_hex(16)}{file_extension}"

    
    file_content_type = file.content_type
    file_path = UPLOAD_DIR / stored_filename
    
    try:
        file_payload = UploadTaskPayload(
            request_id=request_id,
            user_id=user_id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            file_dir=UPLOAD_DIR,
            file_extension=file_extension,
            file_content_type=file_content_type,
            file_path=str(file_path)
        )
    except Exception:
        return APIResponse(
            sucess=False,
            data=None,
            error_code=SYSTEM_ERROR_CODES.FILE_VALIDATION_FAILED.value,
            error_message="File validation failed."
        )
    
    if not file_payload.original_filename:
        return APIResponse(
            sucess=False,
            data=None,
            error_code=USER_ERROR_CODES.UNSUPPORTED_FILE.value,
            error_message="File has no name."
        )


    if file_payload.file_extension not in ALLOWED_EXTENSIONS:
        return APIResponse(
            sucess=False,
            data=None,
            error_code=USER_ERROR_CODES.UNSUPPORTED_FILE.value,
            error_message="File seems sus."
        )
                
    if file_payload.file_content_type not in ALLOWED_MIME_TYPES:
        return APIResponse(
            sucess=False,
            data=None,
            error_code=USER_ERROR_CODES.UNSUPPORTED_FILE.value,
            error_message="Invalid MIME type."
        )
    
    file_bytes: bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        return APIResponse(
            sucess=False,
            data=None,
            error_code=USER_ERROR_CODES.FILE_TOO_BIG.value,
            error_message="File size is biiger than 25mb"
        )        
    kind = filetype.guess(file_bytes)
    if file_payload.file_extension == ".pdf": #check for all like this!
        
        if kind is None or kind.mime != "application/pdf":
            return APIResponse(
                sucess=False,
                data=None,
                error_code=USER_ERROR_CODES.INAPPROPRIATE_FILE.value,
                error_message="Fake PDF detected.."
            )  
            
    responce_data = passed_vlidation_reponce(
        file_payload=file_payload,
        file_bytes=file_bytes
    )
    return APIResponse(
        success=True,
        data=responce_data,
        error_code=None,
        error_message=None
    )


async def save_validated_doc_task_service(payload: passed_vlidation_reponce, db: AsyncSession):
    doc_bytes: bytes = payload.file_bytes
    meta: UploadTaskPayload = payload.file_payload

    try:
        # Save file
        with open(meta.file_path, "wb") as f:
            f.write(doc_bytes)

        document = Document(
            request_id=meta.request_id,
            user_id=meta.user_id,
            original_filename=meta.original_filename,
            stored_filename=meta.stored_filename,
            file_dir=meta.file_dir,
            file_extension=meta.file_extension,
            file_size=len(doc_bytes),
            file_path=meta.file_path,
            mime_type=meta.file_content_type,
            collection_name=DEFAULT_COLLECTION_NAME,
            status=DocumentStatus.UPLOADED,
        )

        db.add(document)

        await db.commit()
        await db.refresh(document)
        
        document_metadata = SavedDocumentPayload.model_validate(document) 
        return document_metadata.model_dump() 

    except Exception:
        await db.rollback()

        if Path(meta.file_path).exists():
            Path(meta.file_path).unlink()

        raise



async def parse_chunk_embed_saved_doc_task2_service(
    doc_meta_obj: SavedDocumentPayload, db: AsyncSession
):
    document = await db.get(
        Document, doc_meta_obj.doc_id
    )  
    if document is None:
        raise UploadingException(
            error_code=SYSTEM_ERROR_CODES.DOCUMENT_NOT_FOUND.value,
            message="Document metadata could not be found.",
        )

    converter = DocumentConverter()
    try:
        result = converter.convert(document.file_path)
        doc = result.document
        document.status = DocumentStatus.PARSED
        await db.commit()


    except Exception as exc:
        document.status = DocumentStatus.FAILED
        document.failure_reason = f"Parsing failed: {str(exc)}"
        await db.commit()

        raise UploadingException(
            error_code=SYSTEM_ERROR_CODES.FILE_PARSE_EXCEPTION.value,
            message="Failed to parse uploaded document.",
        ) from exc
    try:
        max_tokens = Settings.tokenizer_max_tokens
        chunker = (
            HybridChunker( 
                tokenizer=tokenizer_,
                max_tokens=max_tokens,  
                merge_peers=True,  
            )
        )
        chunks = list(chunker.chunk(dl_doc=doc))
        document.chunk_count = len(chunks)
        document.status = DocumentStatus.CHUNKED

        await db.commit()
    except Exception as exc:
        document.status = DocumentStatus.FAILED
        document.failure_reason = f"Chunking failed: {str(exc)}"
        await db.commit()

        raise UploadingException(
            error_code=SYSTEM_ERROR_CODES.FILE_PARSE_EXCEPTION.value,
            message="Failed to chunk parsed document.",
        ) from exc

    try:
        docs = [
            LangChainDocument(
                page_content=chunker.contextualize(chunk),
                metadata={
                    "doc_id": document.doc_id,
                    "request_id": document.request_id,
                    "file_name": document.original_filename,
                    "user_id": document.user_id,
                },
            )
            for chunk in chunks
        ] 
        Chroma.from_documents(
            documents=docs,
            embedding=embedding_model,
            collection_name=document.collection_name,
            persist_directory=Settings.chroma_db_dir,
        )
        document.status = DocumentStatus.READY
        await db.commit()
        await db.refresh(
            document
        ) 

    except Exception as exc:
        document.status = DocumentStatus.FAILED
        document.failure_reason = f"Embedding/Indexing failed: {str(exc)}"
        await db.commit()

        raise UploadingException(
            error_code=SYSTEM_ERROR_CODES.FILE_PARSE_EXCEPTION.value,
            message="Failed to generate embeddings and index document into ChromaDB.",
        ) from exc