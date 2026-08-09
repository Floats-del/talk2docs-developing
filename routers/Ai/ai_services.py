from pathlib import Path
from uuid import uuid4
from fastapi import UploadFile
import filetype
import secrets
from core.Exceptions.exceptions import ChunkingParsedFileException, DocumentNotFoundException, EmbeddingChunkedFileException, ParsingSavedFileException, SavingValidatedFileException, UploadingException
from db_tables.tables import Document
from sqlalchemy import select
from utils.APIResponce_error_code_enum import SYSTEM_ERROR_CODES, USER_ERROR_CODES
from utils.config import settings
from docling.document_converter import DocumentConverter
from utils.schemas import DocumentStatus, SavedDocumentPayload, TokenDataSchema, UploadTaskPayload, APIResponse, passed_vlidation_reponce
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.documents import Document as LangChainDocument #coz ive Document as a db table dont want no mixing
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from docling_core.types.doc import DoclingDocument
from docling_core.transforms.chunker import BaseChunk
from utils.chunker_tokanizer import chunker
from utils.schemas import UploadTask2_fail_cases
import hashlib


converter = DocumentConverter()
max_tokens = settings.tokenizer_max_tokens
model_id = settings.tokenizer
embedding_model = HuggingFaceEmbeddings(
    model_name=settings.embedding_model
)


UPLOAD_DIR = settings.upload_dir
UPLOAD_DIR.mkdir(exist_ok=True, parents=True)
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB
ALLOWED_EXTENSIONS = {
    # PDF
    ".pdf",

    # Microsoft Office
    ".docx",
    ".pptx",
    ".xlsx",

    # OpenDocument
    ".odt",
    ".ods",
    ".odp",

    # Plain text / markup
    ".txt",
    ".text",
    ".md",
    ".qmd",
    ".rmd",
    ".html",
    ".xhtml",
    ".adoc",      # AsciiDoc
    ".asciidoc",
    ".tex",       # LaTeX

    # Structured text
    ".csv",
    ".epub",

    # Email
    ".eml",
    ".msg",
}

ALLOWED_MIME_TYPES = {
    # PDF
    "application/pdf",

    # Microsoft Office
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",       # .docx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",     # .pptx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",             # .xlsx

    # OpenDocument
    "application/vnd.oasis.opendocument.text",           # .odt
    "application/vnd.oasis.opendocument.spreadsheet",    # .ods
    "application/vnd.oasis.opendocument.presentation",   # .odp

    # Plain text / Markdown
    "text/plain",          # .txt, .text
    "text/markdown",       # .md
    "text/html",           # .html
    "application/xhtml+xml", # .xhtml

    # CSV
    "text/csv",

    # EPUB
    "application/epub+zip",

    # Email
    "message/rfc822",      # .eml
    "application/vnd.ms-outlook",  # .msg

    # LaTeX
    "application/x-tex",

    # AsciiDoc (not standardized)
    "text/asciidoc",
    "text/x-asciidoc",

    # Quarto / R Markdown (often uploaded as plain text)
    "text/x-markdown",
}
DEFAULT_COLLECTION_NAME = settings.defualt_collection_name


async def file_validation_service(file: UploadFile, user_jwt_payload: TokenDataSchema, db: AsyncSession) -> APIResponse:
    request_id = str(uuid4())
    user_id = user_jwt_payload.user_id
    
    file_extension = str(Path(file.filename).suffix.lower())
    original_filename = file.filename
    stored_filename = f"{secrets.token_hex(16)}{file_extension}"

    
    file_content_type = file.content_type
    file_path = UPLOAD_DIR / stored_filename
    
    try:
        file_bytes: bytes = await file.read()
        if len(file_bytes) > MAX_FILE_SIZE:
            return APIResponse(
                success=False,
                data=None,
                error_code=USER_ERROR_CODES.FILE_TOO_BIG.value,
                error_message="File size is biiger than 25mb"
            )        
        kind = filetype.guess(file_bytes)
        if file_extension == ".pdf": #check for all like this!
            
            if kind is None or kind.mime != "application/pdf":
                return APIResponse(
                    success=False,
                    data=None,
                    error_code=USER_ERROR_CODES.INAPPROPRIATE_FILE.value,
                    error_message="Fake PDF detected.."
                )  
        
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        stmt = select(Document).where(Document.user_id == user_id, Document.file_hash == file_hash)
        result = await db.execute(stmt)
        existing_document = result.scalar_one_or_none()
        
        if existing_document is not None:
            return APIResponse(
                success=False,
                data=None,
                error_code=USER_ERROR_CODES.DUPLICATE_FILE.value,
                error_message="You have already uploaded this document.",
            )
            
        file_payload = UploadTaskPayload(
            request_id=request_id,
            user_id=user_id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            file_dir=str(UPLOAD_DIR),
            file_hash=file_hash,
            file_extension=file_extension,
            file_content_type=file_content_type,
            file_path=str(file_path)
        )
    except Exception as e:
        print(f"UploadTaskPayload validation error: {e}")
        return APIResponse(
            success=False,
            data=None,
            error_code=SYSTEM_ERROR_CODES.FILE_VALIDATION_FAILED.value,
            error_message="File validation failed."
        )
    
    if not file_payload.original_filename:
        return APIResponse(
            success=False,
            data=None,
            error_code=USER_ERROR_CODES.UNSUPPORTED_FILE.value,
            error_message="File has no name."
        )


    if file_payload.file_extension not in ALLOWED_EXTENSIONS:
        return APIResponse(
            success=False,
            data=None,
            error_code=USER_ERROR_CODES.UNSUPPORTED_FILE.value,
            error_message="File seems sus."
        )
                
    if file_payload.file_content_type not in ALLOWED_MIME_TYPES:
        return APIResponse(
            success=False,
            data=None,
            error_code=USER_ERROR_CODES.UNSUPPORTED_FILE.value,
            error_message="Invalid MIME type."
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
        #Save file
        with open(meta.file_path, "wb") as f:
            f.write(doc_bytes)

        document = Document(
            request_id=meta.request_id,
            user_id=meta.user_id,
            original_filename=meta.original_filename,
            stored_filename=meta.stored_filename,
            file_dir=meta.file_dir,
            file_hash=meta.file_hash,
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

    except Exception as e:
        await db.rollback()

        if Path(meta.file_path).exists():
            Path(meta.file_path).unlink()

        raise SavingValidatedFileException(
            error_code=SYSTEM_ERROR_CODES.SAVING_VALIDATED_FILE_EXCEPTION.value,
            message="Unexpected error saving validated file in dir"
        ) from e





#helper for parse_chunk_embed_saved_doc_task2_service:
def parse_stage(document: Document) -> DoclingDocument:
    result = converter.convert(document.file_path)
    
    document.status = DocumentStatus.PARSED
    doc: DoclingDocument = result.document
    
    return doc

def chunking_stage(document: Document, doc: DoclingDocument) -> list[BaseChunk]:
    chunks = list(chunker.chunk(dl_doc=doc))
    document.chunk_count = len(chunks)
    document.status = DocumentStatus.CHUNKED
    return chunks


#helper for bellow one only!
def build_langchain_doc(document: Document, chunks: list[BaseChunk]) -> list[LangChainDocument]:
    return [
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

def embeding_stage(document: Document, chunks: list[BaseChunk]):
    docs = build_langchain_doc(document=document, chunks=chunks)
    user_id = document.user_id
    user_chroma_dir = (Path(settings.chroma_db_dir) / f"user_{user_id}")
    
    Chroma.from_documents(
        documents=docs,
        embedding=embedding_model,
        collection_name=document.collection_name,
        persist_directory=str(user_chroma_dir),
    )
    document.status = DocumentStatus.READY


async def failed_case(document: Document, db: AsyncSession, reason: Exception, stage: str):
    document.status = DocumentStatus.FAILED
    document.failure_reason = f"{stage} failed: {reason}"
    await db.commit()


async def parse_chunk_embed_saved_doc_task2_service(doc_meta_obj: SavedDocumentPayload, db: AsyncSession):
    document = await db.get(Document, doc_meta_obj.doc_id)  # getting the right doc for user
    if document is None:
        raise DocumentNotFoundException(
            error_code=SYSTEM_ERROR_CODES.DOCUMENT_NOT_FOUND.value,
            message="Document metadata could not be found.",
        )
        
    #1. PARSE STAGE
    try:
        doc: DoclingDocument = parse_stage(document=document)
        await db.commit()

    except Exception as exc:
        await failed_case(document=document, db=db, reason=exc, stage=UploadTask2_fail_cases.PARSING.value)
        raise ParsingSavedFileException(
            error_code=SYSTEM_ERROR_CODES.FILE_PARSE_EXCEPTION.value,
            message="Failed to parse uploaded document.",
        ) from exc



    # 2. CHUNK STAGE
    try:
        chunks = chunking_stage(document=document, doc=doc)
        await db.commit()

    except Exception as exc:
        await failed_case(document=document, db=db, reason=exc, stage=UploadTask2_fail_cases.CHUNKING.value)
        raise ChunkingParsedFileException(
            error_code=SYSTEM_ERROR_CODES.FILE_CHUNKING_EXCEPTION.value,
            message="Failed to chunk parsed document.",
        ) from exc


    # 3. EMBED
    try:
        embeding_stage(document=document, chunks=chunks)
        await db.commit()

    except Exception as exc:
        await failed_case(document=document, db=db, reason=exc, stage=UploadTask2_fail_cases.EMBIDING.value)
        raise EmbeddingChunkedFileException(
            error_code=SYSTEM_ERROR_CODES.FILE_EMBEDING_EXCEPTION.value,
            message="Failed to generate embeddings and index document into ChromaDB.",
        ) from exc