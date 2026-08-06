# Talk2Docs

> Production-ready AI Document Platform built with FastAPI, Celery, Docling, LangChain, ChromaDB, PostgreSQL, and Redis.

Talk2Docs is an asynchronous AI backend that allows users to upload documents, automatically parse, chunk, embed, and index them for Retrieval-Augmented Generation (RAG).

Unlike a simple "Chat with PDF" project, Talk2Docs is designed with production-ready architecture, scalability, and maintainability in mind.

---

# Features

- 📄 Document Upload API
- ⚡ Asynchronous Processing with Celery
- 📚 Docling Document Parsing
- ✂️ Hybrid Semantic Chunking
- 🧠 Embedding Generation
- 🔍 Chroma Vector Database
- 🔐 JWT Authentication
- 🐘 PostgreSQL Metadata Storage
- 🚀 Redis Task Queue
- 📈 Background Processing
- 🛡 Rate Limiting
- 📝 Structured Logging
- ⚠️ Centralized Exception Handling
- 🔄 Async SQLAlchemy
- 🗄 Alembic Migrations
- 🤖 AI-ready Retrieval Pipeline

---

# Architecture

```
                Upload Document
                       │
                       ▼
             FastAPI Validation
                       │
                       ▼
          Celery Worker 1 (Upload)
      ─────────────────────────────────
      • Save file
      • Store metadata
      • Create database record
      • Queue Worker 2
                       │
                       ▼
         Celery Worker 2 (Processing)
      ─────────────────────────────────
      • Parse document using Docling
      • Hybrid Chunking
      • Generate embeddings
      • Store vectors in ChromaDB
      • Update processing status
                       │
                       ▼
              Document Ready
```

---

# Tech Stack

## Backend

- FastAPI
- Python 3.12+
- SQLAlchemy Async
- Pydantic v2
- Alembic

## AI

- Docling
- LangChain
- ChromaDB
- Sentence Transformers
- HybridChunker

## Infrastructure

- Redis
- Celery
- PostgreSQL
- Nginx

## Authentication

- JWT
- OAuth2PasswordBearer

## Utilities

- SlowAPI
- filetype
- Structured Logging

---

# Folder Structure

```
Ai/
    main.py
    retry_logic.py
    intent_classifier.py

celery_worker/
    celery_app.py
    Tasks/
        Ai_worker/
        embedding_worker.py
        ingestion_worker.py
        chat_worker.py

routers/
    Ai/
    auth/
    users/

db_tables/

docling/

vector_db/

core/
    Exceptions/
    rate_limiters/

utils/

alembic/

nigx/
```

---

# Processing Pipeline

## 1. Validation

Every uploaded document is validated for:

- File extension
- MIME type
- Magic bytes (actual file signature)
- Maximum file size

Invalid files never reach the worker queue.

---

## 2. Storage

Worker 1:

- Saves the uploaded file
- Creates metadata
- Inserts a database record
- Dispatches Worker 2

---

## 3. Parsing

Worker 2 converts the document into a structured DoclingDocument.

Supported formats include:

- PDF
- DOCX
- PPTX
- and more...

---

## 4. Chunking

HybridChunker intelligently splits documents into semantic chunks while preserving context and structure.

---

## 5. Embedding

Each chunk is converted into a LangChain Document and embedded using a Sentence Transformer model.

---

## 6. Vector Storage

Embeddings are stored inside ChromaDB.

Each chunk stores metadata such as:

- Document ID
- Request ID
- User ID
- Original Filename

---

# Document Lifecycle

```
UPLOADED

↓

PARSED

↓

CHUNKED

↓

READY
```

If an error occurs:

```
FAILED
```

along with a stored failure reason for debugging.

---

# API Philosophy

Routes remain intentionally thin.

```
Route

↓

Validation

↓

Service

↓

Celery

↓

Database
```

Business logic is isolated from HTTP endpoints, making the project easier to maintain and extend.

---

# Database

PostgreSQL stores:

- Users
- Documents
- Metadata
- Processing Status
- Collection Information

Vectors are stored separately in ChromaDB.

---

# Celery Workers

Current workers:

- Upload Worker
- Parsing Worker

Planned workers:

- Embedding Worker
- Retrieval Worker
- Chat Worker
- Cleanup Worker

Workers communicate using serialized payloads, making them scalable and independent.

---

# Security

- JWT Authentication
- Rate Limiting
- MIME Verification
- Magic Byte Validation
- Structured Exception Handling
- Async Database Operations

---

# Current Progress

- ✅ Authentication
- ✅ Upload API
- ✅ Validation Pipeline
- ✅ PostgreSQL Integration
- ✅ Redis Integration
- ✅ Celery Workers
- ✅ Docling Parsing
- ✅ Hybrid Chunking
- ✅ ChromaDB Integration
- ✅ Processing Status Tracking
- ✅ Structured Error Handling

---

# Planned Features

## Retrieval

- Hybrid Search
- Vector Search
- BM25 Retrieval
- Reciprocal Rank Fusion (RRF)

---

## AI

- Chat with Documents
- Multi-turn Conversations
- Source Citation
- Query Expansion
- Query Rewriting

---

## Multi-user Support

- User Collections
- Workspace Isolation
- Permission Management

---

## Workspace

- Multiple Documents
- Folder Management
- Collection Support

---

## Background Processing

- Task Progress Tracking
- Retry Policies
- Queue Priorities
- Worker Monitoring

---

## OCR

Support for:

- Images
- Scanned PDFs

---

## Future AI Features

- AI Summarization
- Keyword Extraction
- Entity Recognition
- Semantic Search
- Automatic Document Titles
- AI Notes
- Flashcard Generation
- Quiz Generation

---

# Roadmap

## Phase 1

- Upload
- Parse
- Chunk
- Embed
- Index

## Phase 2

- Hybrid Retrieval
- Chat Endpoint

## Phase 3

- Conversation Memory
- Session Management

## Phase 4

- Streaming Responses

## Phase 5

- Docker
- Kubernetes
- CI/CD
- Monitoring
- Production Deployment

---

# Design Philosophy

Talk2Docs is built around a production-first architecture.

Instead of processing everything inside a single request, computationally expensive operations are delegated to asynchronous Celery workers. Each worker has a single responsibility and communicates through serialized payloads.

This approach makes the system easier to scale, monitor, and extend while keeping API responses fast and reliable.

The project emphasizes:

- Clean Architecture
- Thin Routes
- Async Processing
- Fault Tolerance
- Scalable AI Pipelines

---

# License

MIT License

---

Built with ❤️ using FastAPI, Docling, Celery, LangChain, ChromaDB, PostgreSQL, and Redis.