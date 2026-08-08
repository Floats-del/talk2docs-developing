# Talk2Docs

> **Production-oriented AI document processing and RAG backend built with FastAPI, Celery, Docling, LangChain, ChromaDB, PostgreSQL, and Redis.**

Talk2Docs is an asynchronous AI document platform designed to turn uploaded documents into searchable, user-isolated knowledge for Retrieval-Augmented Generation (RAG).

The system separates HTTP request handling from computationally expensive document processing using **Celery workers**, while PostgreSQL tracks document state and ChromaDB stores vector representations.

The goal is not simply to build a "Chat with PDF" application, but to build a backend that can evolve into a scalable AI document platform.

---

# ✨ Features

* 📄 Asynchronous document upload
* ⚡ Celery background processing
* 📚 Docling document parsing
* ✂️ Structure-aware document chunking
* 🧠 Embedding generation
* 🔍 ChromaDB vector storage
* 🔐 JWT authentication
* 🐘 PostgreSQL metadata storage
* 🚀 Redis broker/result backend
* 📊 Document processing state tracking
* 🔄 Async SQLAlchemy
* 🛡 Rate limiting
* 📝 Structured logging
* ⚠️ Centralized exception handling
* 🗃 Alembic database migrations
* 🔒 User-isolated document retrieval
* 🤖 RAG-ready retrieval architecture

---

# 🏗 Architecture

Talk2Docs separates the API request lifecycle from heavy document-processing workloads.

```text
                    Client
                      │
                      ▼
                FastAPI API
                      │
                      ▼
              File Validation
                      │
                      ▼
              Upload Worker
                      │
          ┌───────────┴───────────┐
          │                       │
          ▼                       ▼
     Save File              PostgreSQL
          │                  Metadata
          │
          ▼
          Processing Worker
                │
                ▼
             Docling
                │
                ▼
             Chunking
                │
                ▼
            Embeddings
                │
                ▼
             ChromaDB
                │
                ▼
          Document Ready
```

The API does not perform expensive parsing, chunking, or embedding work directly inside the request lifecycle.

---

# 🔄 Document Processing Pipeline

## 1. File Validation

Before a document reaches Celery, the upload service validates:

* File name
* File extension
* MIME type
* File size
* File signatures / magic bytes
* User identity

Invalid files are rejected before entering the background-processing pipeline.

---

## 2. Upload Worker

The first Celery worker is responsible for persisting the validated upload.

It:

1. Receives the validated payload.
2. Saves the file to storage.
3. Creates the `Document` database record.
4. Commits the metadata.
5. Passes the resulting document metadata to the processing worker.

The API immediately returns a Celery `task_id` instead of waiting for the document-processing pipeline to finish.

---

## 3. Document Processing Worker

The processing worker performs the expensive document operations:

```text
Document
   │
   ▼
Docling Parsing
   │
   ▼
Chunking
   │
   ▼
Embedding Generation
   │
   ▼
ChromaDB
```

Each stage has its own exception handling and failure tracking.

---

## 4. Processing Status

PostgreSQL acts as the persistent source of truth for document processing state.

The document lifecycle is tracked independently from Celery's task state.

```text
UPLOADED
   │
   ▼
PROCESSING
   │
   ├── PARSE
   ├── CHUNK
   └── EMBED
   │
   ▼
READY
```

If a processing stage fails:

```text
FAILED
   │
   └── failure_reason
```

This allows the system to retain useful information even after the Celery task has completed or exhausted its retries.

---

# 📡 Worker Status & Polling

Uploads are asynchronous, so clients can poll the worker status endpoint:

```text
GET /upload_worker/{task_id}/{request_id}
```

The endpoint combines two sources of information:

### Redis / Celery

Used for transient worker execution state:

```text
PENDING
STARTED
RETRY
SUCCESS
FAILURE
```

### PostgreSQL

Used for persistent document state:

```text
PENDING_SAVE
UPLOADED
PROCESSING
READY
FAILED
```

This distinction is intentional.

**Celery tells us what the worker is doing.**

**PostgreSQL tells us what happened to the document.**

The polling response combines both.

```json
{
    "worker": {
        "status": "processing",
        "task_id": "...",
        "state": "STARTED"
    },
    "document": {
        "status": "UPLOADED",
        "failure_reason": null
    }
}
```

If polling occurs before Worker 1 has created the database record, the document status is reported as:

```text
PENDING_SAVE
```

rather than incorrectly treating the document as missing.

---

# 🧠 Retrieval Architecture

Once documents have been indexed, Talk2Docs can retrieve only the information belonging to the requesting user.

The planned retrieval pipeline is:

```text
User Query
    │
    ├───────────────┐
    ▼               ▼
Vector Search     BM25 Search
    │               │
    └───────┬───────┘
            ▼
       Hybrid Retrieval
            │
            ▼
       Result Fusion
            │
            ▼
          Top-K
            │
            ▼
       AI Context
```

Document metadata contains identifiers such as:

* `user_id`
* `document_id`
* `request_id`
* `collection_name`

User-level metadata filtering is used to maintain document isolation during retrieval.

---

# 🛠 Tech Stack

## Backend

* Python 3.12+
* FastAPI
* Pydantic v2
* SQLAlchemy Async
* Alembic

## Document Processing

* Docling
* HybridChunker

## AI / RAG

* LangChain
* Sentence Transformers
* ChromaDB
* Vector Retrieval
* BM25 Retrieval
* Hybrid Retrieval

## Background Processing

* Celery
* Redis

## Database

* PostgreSQL

## Authentication & Security

* JWT
* OAuth2PasswordBearer
* SlowAPI rate limiting
* MIME validation
* File signature validation
* User-scoped document access

## Infrastructure

* Nginx

---

# 📁 Project Structure

```text
Talk2Docs/
│
├── Ai/
│   ├── main.py
│   ├── retry_logic.py
│   └── intent_classifier.py
│
├── celery_worker/
│   ├── celery_app.py
│   └── Tasks/
│       ├── Ai_worker/
│       ├── embedding_worker.py
│       ├── ingestion_worker.py
│       └── chat_worker.py
│
├── routers/
│   ├── Ai/
│   ├── auth/
│   └── users/
│
├── db_tables/
│
├── docling/
│
├── vector_db/
│
├── core/
│   ├── Exceptions/
│   └── rate_limiters/
│
├── utils/
│
├── alembic/
│
└── nigx/
```

---

# 🗄 Database

PostgreSQL stores persistent application and document metadata.

The `Document` model tracks information such as:

* Document ID
* User ID
* Request ID
* Original filename
* Stored filename
* File path
* File extension
* MIME type
* File size
* Collection name
* Chunk count
* Processing status
* Failure reason
* Embedding model
* File hash
* Upload timestamp
* Processing timestamp

Vector embeddings are stored separately in ChromaDB.

---

# 🔐 Security & Isolation

Talk2Docs treats uploaded documents as user-owned resources.

The system uses:

* JWT authentication
* User-scoped database queries
* User-scoped vector retrieval
* Rate limiting
* File extension validation
* MIME validation
* Magic-byte validation
* Maximum upload size limits
* Centralized exception handling

For example, document lookup is scoped by both:

```text
request_id
+
authenticated user_id
```

This prevents a user from retrieving another user's document simply by knowing its request ID.

---

# ⚠️ Error Handling

Application-level failures use custom exceptions derived from a common application exception hierarchy.

Examples include:

```text
DocumentNotFoundException
SavingValidatedFileException
ParsingSavedFileException
ChunkingParsedFileException
EmbeddingChunkedFileException
InvalidTask1PayloadException
InvalidTask2PayloadException
```

Worker failures are separated from HTTP request failures.

The API request can finish successfully while background processing continues independently.

Celery retries transient failures according to worker-specific retry policies.

---

# 🔁 Worker Design

Workers communicate using serialized payloads rather than passing ORM objects between processes.

The current upload pipeline follows:

```text
FastAPI
   │
   ▼
Task 1
   │
   ├── Save file
   ├── Create Document
   └── Start Task 2
             │
             ▼
          Task 2
             │
             ├── Parse
             ├── Chunk
             └── Embed
```

This keeps workers independently executable and avoids coupling Celery tasks to SQLAlchemy session state.

---

# 🧱 API Design Philosophy

Routes are intentionally kept thin.

```text
HTTP Route
    │
    ▼
Service Layer
    │
    ▼
Celery Worker
    │
    ▼
Database / Vector Store
```

The API layer is responsible for:

* Request handling
* Authentication
* Validation
* Rate limiting
* Starting workers
* Returning worker status

Business logic lives in services and worker tasks.

---

# 📈 Current Progress

### Core Backend

* ✅ FastAPI application
* ✅ Async SQLAlchemy
* ✅ PostgreSQL
* ✅ Alembic migrations
* ✅ JWT authentication
* ✅ Redis integration
* ✅ Celery integration
* ✅ Rate limiting
* ✅ Centralized exception handling
* ✅ Structured logging

### Document Pipeline

* ✅ File validation
* ✅ File storage
* ✅ Document metadata persistence
* ✅ Asynchronous upload worker
* ✅ Document processing worker
* ✅ Docling parsing
* ✅ Document chunking
* ✅ Embedding generation
* ✅ ChromaDB indexing
* ✅ Processing status tracking
* ✅ Celery retry handling
* ✅ Redis + PostgreSQL worker status polling

### Retrieval

* 🚧 Global retrieval helper
* 🚧 Hybrid retrieval
* 🚧 BM25 + vector search
* 🚧 Result fusion
* 🚧 Top-K context generation
* 🚧 RAG prompt integration

---

# 🗺 Roadmap

## Phase 1 — Ingestion

* [x] Upload validation
* [x] File persistence
* [x] Document metadata
* [x] Docling parsing
* [x] Chunking
* [x] Embedding
* [x] ChromaDB indexing

## Phase 2 — Retrieval

* [ ] Global retrieval service
* [ ] Vector retrieval
* [ ] BM25 retrieval
* [ ] Hybrid retrieval
* [ ] Reciprocal Rank Fusion
* [ ] Top-K context selection
* [ ] User-isolated retrieval

## Phase 3 — RAG

* [ ] AI query pipeline
* [ ] Context injection
* [ ] Document-grounded responses
* [ ] Source citations
* [ ] Query rewriting
* [ ] Query expansion

## Phase 4 — Conversations

* [ ] Multi-turn conversations
* [ ] Conversation memory
* [ ] Session management
* [ ] Streaming responses

## Phase 5 — Platform

* [ ] Workspace support
* [ ] Multiple document collections
* [ ] Permission management
* [ ] OCR
* [ ] Background task monitoring
* [ ] Queue prioritization

## Phase 6 — Production Infrastructure

* [ ] Docker
* [ ] CI/CD
* [ ] Monitoring
* [ ] Distributed deployment
* [ ] Kubernetes
* [ ] Production observability

---

# 🎯 Design Philosophy

Talk2Docs is being developed with a **production-first mindset**.

The project intentionally avoids putting the entire document pipeline inside a single HTTP request.

Instead:

```text
FastAPI
   │
   ├── Authentication
   ├── Validation
   └── Task Dispatch
             │
             ▼
          Celery
             │
             ├── File Processing
             ├── Document Parsing
             ├── Chunking
             └── Embedding
                     │
                     ▼
                 Data Layer
                 ┌───────┐
                 │ Postgres
                 │ ChromaDB
                 │ Redis
                 └───────┘
```

The architecture prioritizes:

* **Separation of concerns**
* **Thin API routes**
* **Asynchronous processing**
* **Fault tolerance**
* **User isolation**
* **Scalability**
* **Maintainability**
* **AI/RAG extensibility**

The long-term goal is to evolve Talk2Docs from a document-ingestion backend into a complete AI-powered document intelligence platform.

---

# 📜 License

MIT License

---

Built with ❤️ using **FastAPI · Celery · Docling · LangChain · ChromaDB · PostgreSQL · Redis**
