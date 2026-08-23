import asyncio
from langchain_chroma import Chroma
from utils.logging.helper_log import log_state
from utils.logging.logEvents import RetriverLog
from langchain_classic.retrievers.ensemble import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document as LangChainDocument
import time 

embedding_lock = asyncio.Lock()
async def safe_retrieve(retriever, query: str) -> list[LangChainDocument]:
  """Thread-safe wrapper for retriever.ainvoke to prevent

  'Already borrowed' Rust tokenizer panics during asyncio.gather.
  """
  async with embedding_lock:
    return await retriever.ainvoke(query)


def format_tiered_context(docs: list[LangChainDocument]) -> str:
    """Formats up to 5 retrieved docs into explicit Tier hierarchy blocks."""

    tier_labels = [
        "TIER 1: PRIMARY TRUTH (Highest Relevance)",
        "TIER 2: SUPPORTING HELPER (Secondary Relevance)",
        "TIER 3: GENERAL CONTEXT (Background 1)",
        "TIER 4: GENERAL CONTEXT (Background 2)",
        "TIER 5: GENERAL CONTEXT (Background 3)",
    ]

    formatted_chunks = []

    for idx, doc in enumerate(docs[:5]):
        label = tier_labels[idx] 
        metadata = doc.metadata or {} 
        file_name = metadata.get("file_name", "Unknown Source") 
                                                                
    
        rerank_score = metadata.get("rerank_score")
        quote = metadata.get("key_evidence_quote")
        reasoning = metadata.get("rerank_reasoning")


        extra_lines = []
        if rerank_score is not None:
            extra_lines.append(f"Relevance Score: {rerank_score:.2f}")
        if quote:
            extra_lines.append(f"Key Evidence: \"{quote}\"")
        if reasoning:
            extra_lines.append(f"Reasoning: {reasoning}")

        #and this will be "" 
        extra_info_str = ("\n" + "\n".join(extra_lines)) if extra_lines else ""

        chunk_entry = (
            f"=== [{label}] ===\n" #the label 
            f"Source File: {file_name}\n" #file name
            f"{extra_info_str}\n" #enriched metadata line(s) if reranker succeeded!
            f"Content: {doc.page_content}" #the doc's page_content!
        )
        formatted_chunks.append(chunk_entry) 
    return "\n\n".join(formatted_chunks) 



async def build_get_retriever(user_vdb: Chroma, user_id: int, doc_name: list[str] | None = None, k: int = 20) -> EnsembleRetriever | None:
    log_state(RetriverLog.BUILDING_RETRIVER_STARTED, function="build_get_retriever", user_id=user_id)
    
    
    # 1. Fetch documents from user's Chroma collection for BM25
    if isinstance(doc_name, str):
        doc_name = [doc_name]
    
    where_filter = {"file_name": {"$in": doc_name}} if doc_name and len(doc_name) > 0 else None 



    log_state(RetriverLog.FETCHING_DOCS_FOR_BM25, function="build_get_retriever", user_id=user_id)
    chroma_data = await asyncio.to_thread(user_vdb.get,
        where=where_filter,
        include=["documents", "metadatas"] 
    ) 
        

    log_state(RetriverLog.FETCHING_DOCS_FOR_BM25, function="build_get_retriever", user_id=user_id)
    raw_texts = chroma_data.get("documents") or [] 
    raw_metadatas = chroma_data.get("metadatas") or [] 


    # Safeguard: return None if user has no documents in this collection
    if not raw_texts: 
        log_state(RetriverLog.COULD_NOT_FIND_DOCS_FOR_BM25, function="build_get_retriever", user_id=user_id)
        log_state(RetriverLog.BUILDING_RETRIVER_FAILURE, function="build_get_retriever", user_id=user_id)
        log_state(RetriverLog.EXITING_RETRIVER_BUILDER, function="build_get_retriever", user_id=user_id)
        return None


    # Reconstruct true LangChain Document instances expected by BM25
    bm25_docs = [
        LangChainDocument(page_content=text, metadata=meta or {}) 
        for text, meta in zip(raw_texts, raw_metadatas) 
        if text and text.strip()
    ]
    
    if not bm25_docs:
        log_state(RetriverLog.COULD_NOT_CONVERT_DOCS_FOR_BM25, function="build_get_retriever", user_id=user_id)
        log_state(RetriverLog.BUILDING_RETRIVER_FAILURE, function="build_get_retriever", user_id=user_id)
        log_state(RetriverLog.EXITING_RETRIVER_BUILDER, function="build_get_retriever", user_id=user_id)
        return None 


    try:
        log_state(RetriverLog.BUILDING_BM25, function="build_get_retriever", user_id=user_id)
        #same here instead of func() we pass func name, parameters
        bm25_retriever = await asyncio.to_thread(BM25Retriever.from_documents,
            documents=bm25_docs,
            k=k,
        ) #fetching by words retriver 
    except Exception:
        log_state(RetriverLog.BUILDING_BM25_FAILURE, function="build_get_retriever", user_id=user_id)
        return None
    
    
    log_state(RetriverLog.BUILDING_BM25_SUCCESS, function="build_get_retriever", user_id=user_id)
        

    
    
    # 2. Build Vector Retriever
    search_kwargs = {"k": k}
    if where_filter:
        search_kwargs["filter"] = where_filter

    try:
        log_state(RetriverLog.BUILDING_VECTOR_RETRIVER, function="build_get_retriever", user_id=user_id)
        vector_retriever = user_vdb.as_retriever(
            search_type="similarity",
            search_kwargs=search_kwargs,
        ) #fetching by embeddings ;) ++ accuracy
    except Exception:
        log_state(RetriverLog.BUILDING_VECTOR_RETRIVER_FAILURE, function="build_get_retriever", user_id=user_id)
        return None

    log_state(RetriverLog.BUILDING_VECTOR_RETRIVER_SUCCESS, function="build_get_retriever", user_id=user_id)


    try:
        log_state(RetriverLog.CREATING_HYBRID_RETRIVER, function="build_get_retriever", user_id=user_id)
        # 3. Combine both into Hybrid Ensemble Retriever
        hybrid_retirver = EnsembleRetriever(
            retrievers=[vector_retriever, bm25_retriever],
            weights=[0.5, 0.5],
            c=60,
        )# cobining rsult of both 50/50 and we return a mega retriver!
    except Exception:
        log_state(RetriverLog.CREATING_HYBRID_RETRIVER_FAILURE, function="build_get_retriever", user_id=user_id)
        return None
    log_state(RetriverLog.CREATING_HYBRID_RETRIVER_SUCCESS, function="build_get_retriever", user_id=user_id)
    log_state(RetriverLog.BUILDING_RETRIVER_SUCCESS, function="build_get_retriever", user_id=user_id)
    log_state(RetriverLog.EXITING_RETRIVER_BUILDER, function="build_get_retriever", user_id=user_id)
    return hybrid_retirver
   