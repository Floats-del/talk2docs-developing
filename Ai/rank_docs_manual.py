import re

from utils.APIResponce_error_code_enum import USER_ERROR_CODES, SYSTEM_ERROR_CODES
from typing import Annotated, Any, Literal, Optional
from langchain_core.prompts import ChatPromptTemplate, FewShotChatMessagePromptTemplate
from langsmith import traceable
from pydantic import BaseModel, Field, StringConstraints, field_validator, ConfigDict
from Ai.retry_logic import check_provider_quota
from langchain_core.output_parsers import PydanticOutputParser
from core.Exceptions.exceptions import AIServiceException
from utils.logging.logEvents import ExceptionLog, MappingReReankLog, ProviderLog, ReRanklog, RepairLog, SecurityLog, ServiceLog
from utils.schemas import APIResponse, QuestionRequest
from Ai.intent_classifier_manul import  get_user_intent
from pydantic import ValidationError
from Ai.raw_and_parsed_clean import extract_raw_data, extract_parsed_data
from utils.logging.helper_log import log_state, LogState 
from langchain_chroma import Chroma
from langchain_classic.retrievers.ensemble import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document as LangChainDocument
import asyncio
import json 
import traceback 



CandidateIDStr = Annotated[
    str,
    StringConstraints(
        pattern=r"^candidate_\d+$",
        strip_whitespace=True,
    ),
]


class CandidateEvaluation(BaseModel):
    """Detailed evaluation and evidence score for an individual retrieved document chunk."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    candidate_id: CandidateIDStr = Field(
        ...,
        title="Candidate Identifier",
        description="The exact identifier tag assigned to the candidate chunk (e.g., 'candidate_0', 'candidate_1').",
        examples=["candidate_0", "candidate_12"],
    )

    relevance_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        title="Primary Relevance Score",
        description=(
            "PRIMARY SORTING KEY (0.0 to 1.0). Overall evidence utility for answering the question. "
            "Higher relevance MUST always beat higher directness."
        ),
    )

    directness_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        title="Diagnostic Directness Score",
        description=(
            "DIAGNOSTIC METRIC ONLY (0.0 to 1.0). Indicates if the chunk contains direct statements "
            "versus supporting context. Does NOT override relevance_score."
        ),
    )

    key_evidence_quote: Optional[str] = Field(
        default=None,
        title="Verbatim Source Quote",
        description=("The quote must contain only words and characters taken from the candidate text.",
                    "Do not paraphrase, summarize, rewrite, or invent content.",
                    "Whitespace differences such as newlines vs spaces are acceptable."
        ),
    )

    @field_validator("relevance_score", "directness_score")
    @classmethod
    def round_score(cls, v: float) -> float:
        return round(v, 2)





class RerankResult(BaseModel):
    """Structured output container for the AI Reranker step."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "ranked_candidates": [
                        {
                            "candidate_id": "candidate_3",
                            "relevance_score": 0.98,
                            "directness_score": 0.95,
                            "key_evidence_quote": "max_retries is defaulted to 3 inside worker.py",
                        }
                    ]
                }
            ]
        },
    )

    ranked_candidates: list[CandidateEvaluation] = Field(
        ...,
        title="Ranked Candidates",
        description="List of candidate document evaluations ordered in descending order of relevance score (highest to lowest; ties allowed).",
    )


def aggressive_normalize(text: str) -> str:
  """Strips markdown, emojis, special symbols, and normalizes whitespace."""
  if not text:
    return ""
  text = text.lower()
  text = re.sub(r"[*_#~`>]+", " ", text)
  text = re.sub(r"[^\w\s.,;:?!-]", " ", text)
  return re.sub(r"\s+", " ", text).strip()



def validate_rerank_result(result: RerankResult | None, received_docs: list[LangChainDocument], user_id: int) -> bool:
    """Validates that a RerankResult strictly satisfies our buisness logic,
    relevance sorting order, and verbatim evidence quote accuracy.
    """
    log_state(ReRanklog.VALIDATING_RERANK_RESULT_STARTED, function="validate_rerank_result", user_id=user_id)
    
    if not result or not result.ranked_candidates:
        log_state(ReRanklog.VALIDATING_RERANK_RESULT_FAILURE, function="validate_rerank_result", user_id=user_id)
        log_state(ReRanklog.EXITING_VALIDATING_RERANK_FUNCTION, function="validate_rerank_result", user_id=user_id)
        return False

    expected_ids = {f"candidate_{i}" for i in range(len(received_docs))} 
    returned_ids = [eval_item.candidate_id for eval_item in result.ranked_candidates] 

    if len(returned_ids) != len(set(returned_ids)):
        log_state(ReRanklog.DUPLICATE_CANDIDATE_IDS_DETECTED, function="validate_rerank_result", user_id=user_id)
        log_state(ReRanklog.VALIDATING_RERANK_RESULT_FAILURE, function="validate_rerank_result", user_id=user_id)
        log_state(ReRanklog.EXITING_VALIDATING_RERANK_FUNCTION, function="validate_rerank_result", user_id=user_id)
        return False 

    if set(returned_ids) != expected_ids:
        log_state(ReRanklog.CANDIDATE_IDS_MISMATCH, function="validate_rerank_result", user_id=user_id)
        log_state(ReRanklog.VALIDATING_RERANK_RESULT_FAILURE, function="validate_rerank_result", user_id=user_id)
        log_state(ReRanklog.EXITING_VALIDATING_RERANK_FUNCTION, function="validate_rerank_result", user_id=user_id)
        return False 

    scores = [eval_item.relevance_score for eval_item in result.ranked_candidates] 
    if scores != sorted(scores, reverse=True): 
        log_state(ReRanklog.RELEVANCE_SCORES_NOT_DESCENDING, function="validate_rerank_result", user_id=user_id)
        log_state(ReRanklog.VALIDATING_RERANK_RESULT_FAILURE, function="validate_rerank_result", user_id=user_id)
        log_state(ReRanklog.EXITING_VALIDATING_RERANK_FUNCTION, function="validate_rerank_result", user_id=user_id)
        return False
    
    doc_map: dict = {f"candidate_{i}": doc for i, doc in enumerate(received_docs)} 
    
    for eval_item in result.ranked_candidates: 
        quote = eval_item.key_evidence_quote
        
        if quote is not None: 
                                
            if not quote.strip(): 
                log_state(ReRanklog.RERANK_EVIDENCE_QUOTE_EMPTY, function="validate_rerank_result", user_id=user_id)
                log_state(ReRanklog.VALIDATING_RERANK_RESULT_FAILURE, function="validate_rerank_result", user_id=user_id)
                log_state(ReRanklog.EXITING_VALIDATING_RERANK_FUNCTION, function="validate_rerank_result", user_id=user_id)
                return False
                                
            original_text = doc_map[eval_item.candidate_id].page_content 
                                                                            
            norm_quote = aggressive_normalize(quote)
            norm_source = aggressive_normalize(original_text)
            print("QUOTE:", repr(norm_quote))
            print("SOURCE:", repr(norm_source))
            
            if norm_quote not in norm_source:
                log_state(ReRanklog.EVIDENCE_QUOTE_NOT_FOUND_IN_SOURCE, function="validate_rerank_result", user_id=user_id)
                log_state(ReRanklog.VALIDATING_RERANK_RESULT_FAILURE, function="validate_rerank_result", user_id=user_id)
                log_state(ReRanklog.EXITING_VALIDATING_RERANK_FUNCTION, function="validate_rerank_result", user_id=user_id)
                return False 
            
    log_state(ReRanklog.VALIDATING_RERANK_RESULT_SUCCESS, function="validate_rerank_result", user_id=user_id)
    log_state(ReRanklog.EXITING_VALIDATING_RERANK_FUNCTION, function="validate_rerank_result", user_id=user_id)
    return True


def map_rerank_result_to_docs(result: RerankResult, received_docs: list[LangChainDocument], top_k: int, user_id: int) -> list[LangChainDocument] | None:
    """Maps candidate IDs back to original LangChainDocument objects, enriches metadata,
    and returns the top_k docs.
    """
    log_state(MappingReReankLog.MAPPING_RERANKED_STARTED, function="map_rerank_result_to_docs", user_id=user_id)
    
    doc_map = {f"candidate_{i}": doc for i, doc in enumerate(received_docs)} 
    
    reranked_docs: list[LangChainDocument] = []

    try:
        for eval_item in result.ranked_candidates[:top_k]: 
            
            original_doc = doc_map[eval_item.candidate_id] 
            
            updated_metadata = dict(original_doc.metadata or {})
            updated_metadata["rerank_score"] = eval_item.relevance_score
            updated_metadata["directness_score"] = eval_item.directness_score
            updated_metadata["key_evidence_quote"] = eval_item.key_evidence_quote

            reranked_docs.append(
                LangChainDocument(
                    page_content=original_doc.page_content,
                    metadata=updated_metadata,
                )
            ) 
    except Exception as e :
        log_state(MappingReReankLog.MAPPING_RERANKED_FAILURE, level=LogState.EXCEPTION, function="map_rerank_result_to_docs", exc=e, user_id=user_id)
        log_state(MappingReReankLog.EXITING_MAPPING_RERANKED_FUNCTION, function="map_rerank_result_to_docs", user_id=user_id)
        return None
    
    log_state(MappingReReankLog.MAPPING_RERANKED_SUCCESS, function="map_rerank_result_to_docs", user_id=user_id)
    log_state(MappingReReankLog.EXITING_MAPPING_RERANKED_FUNCTION, function="map_rerank_result_to_docs", user_id=user_id)
    return reranked_docs


def build_candidate_text(documents: list[LangChainDocument]) -> str:
    candidates = []

    for index, doc in enumerate(documents):
        metadata = doc.metadata or {}

        source = metadata.get("file_name", "Unknown")
        page = metadata.get("page_number")

        page_info = f", Page: {page}" if page is not None else ""

        candidates.append(
            f"[candidate_{index}] "
            f"(Source: {source}{page_info})\n"
            f"Content:\n"
            f"{doc.page_content}"
        )

    return "\n\n---\n\n".join(candidates)


async def re_rank_docs(model, question: str, received_docs: list[LangChainDocument], user_id: int, top_k: int):
    log_state(ServiceLog.AI_SERVICE_STARTED, function="re_rank_docs", user_id=user_id) 
    
    if not question or not question.strip():
        log_state(SecurityLog.EMPTY_INPUT, function="re_rank_docs", user_id=user_id)
        log_state(ServiceLog.AI_SERVICE_FAILED, function="re_rank_docs", user_id=user_id)
        log_state(ServiceLog.EXITING_AI_SERVICE, function="re_rank_docs", user_id=user_id)
        
        return APIResponse(
            success=False,
            data=None,
            error_code=USER_ERROR_CODES.EMPTY_INPUT.value,
            error_message="Input text is empty"
        )
    
    if not received_docs:
        log_state(ServiceLog.AI_SERVICE_FAILED, function="re_rank_docs", user_id=user_id)
        log_state(ServiceLog.EXITING_AI_SERVICE, function="re_rank_docs", user_id=user_id)     
        return APIResponse(
            success=False,
            data=None,
            error_code=SYSTEM_ERROR_CODES.NO_DATA_WAS_SENT_TO_RANKER.value,
            error_message="Re-ranker got no data, meaning retriver goofed"
        )
    
    parser = PydanticOutputParser(pydantic_object=RerankResult)
    
    SYSTEM_TEMPLATE = r"""\
        You are an expert AI Evidence Reranker and Information Retrieval Specialist.

        YOUR MANDATE:
        Evaluate candidate document chunks and rank them based on how effectively they satisfy the user's query.

        CRITICAL OPERATIONAL RULES:

        1. CANDIDATE COVERAGE & INTEGRITY (1:1 CONTRACT):
        - `ranked_candidates` MUST contain EXACTLY ONE evaluation entry for EVERY candidate provided in the input prompt.
        - NO OMISSIONS: Every candidate provided must be scored and included, even if completely irrelevant (assign a low relevance_score).
        - NO DUPLICATES: No candidate ID may appear more than once in `ranked_candidates`.
        - NO HALLUCINATIONS: Do NOT invent or alter candidate IDs. Only use candidate IDs present in the input (e.g., 'candidate_0', 'candidate_1').

        2. DO NOT GENERATE AN ANSWER:
        - Do not answer or summarize the user's question.
        - Only evaluate and rank the provided candidate chunks.

        3. RELEVANCE VS DIRECTNESS RANKING:
        - `relevance_score` (0.00 to 1.00) is the PRIMARY ranking metric. Sort `ranked_candidates` in descending order of `relevance_score` (highest to lowest; ties are allowed).
        - `directness_score` (0.00 to 1.00) is purely DIAGNOSTIC. A highly direct chunk with incomplete facts MUST be scored lower in `relevance_score` than a less direct chunk containing complete evidence.

        4. VERBATIM EVIDENCE QUOTING:
        - `key_evidence_quote` MUST be an exact, character-for-character verbatim quote from the candidate text, or `null` if irrelevant. Do not paraphrase.

        OUTPUT REQUIREMENTS:
        - Return ONLY the fields defined by the provided schema.
        - `ranked_candidates` MUST contain exactly one evaluation for every candidate.
        - Do not add any additional fields.

        {format_instructions}
        """
        
    FEW_SHOT_EXAMPLES = [
    {
        "question": "What is the default retry limit for Redis tasks in worker.py?",
        "candidate_text": (
            "[candidate_0] (Source: celery_config.py, Page: 12)\n"
            "Content:\n"
            "Celery brokers support various retry backoff mechanisms. Redis backoff defaults to exponential.\n\n"
            "---\n\n"
            "[candidate_1] (Source: worker.py, Page: 4)\n"
            "Content:\n"
            "class TaskWorker:\n"
            "    def __init__(self):\n"
            "        self.max_retries = 3  # Default Redis connection retry limit\n"
            "        self.timeout = 30\n\n"
            "---\n\n"
            "[candidate_2] (Source: worker.py, Page: 2)\n"
            "Content:\n"
            "Worker startup log initialized. Connecting to Redis cluster."
        ),
        "output": json.dumps(
            {
                "ranked_candidates": [
                    {
                        "candidate_id": "candidate_1",
                        "relevance_score": 0.98,
                        "directness_score": 0.95,
                        "key_evidence_quote": "self.max_retries = 3  # Default Redis connection retry limit",
                    },
                    {
                        "candidate_id": "candidate_0",
                        "relevance_score": 0.35,
                        "directness_score": 0.20,
                        "key_evidence_quote": None,
                    },
                    {
                        "candidate_id": "candidate_2",
                        "relevance_score": 0.10,
                        "directness_score": 0.10,
                        "key_evidence_quote": None,
                    },
                ],
            }
        ),
    },
    {
        "question": "Why did the Q3 database migration fail during deployment?",
        "candidate_text": (
            "[candidate_0] (Source: deployment_logs.txt, Page: 1)\n"
            "Content:\n"
            "CRITICAL: Q3 Database migration failed on 2026-07-15 at 14:22 UTC.\n\n"
            "---\n\n"
            "[candidate_1] (Source: postmortem_q3.md, Page: 2)\n"
            "Content:\n"
            "Root Cause Analysis: During the Q3 schema migration, an unindexed alter query on the 'users' table caused exclusive lock contention, leading to connection pool exhaustion and subsequent task timeout.\n\n"
            "---\n\n"
            "[candidate_2] (Source: database_schema.sql, Page: 45)\n"
            "Content:\n"
            "CREATE TABLE users (id SERIAL PRIMARY KEY, email VARCHAR(255) NOT NULL);"
        ),
        "output": json.dumps(
            {
                "ranked_candidates": [
                    {
                        "candidate_id": "candidate_1",
                        "relevance_score": 0.96,
                        "directness_score": 0.90,
                        "key_evidence_quote": "an unindexed alter query on the 'users' table caused exclusive lock contention, leading to connection pool exhaustion",
                    },
                    {
                        "candidate_id": "candidate_0",
                        "relevance_score": 0.45,
                        "directness_score": 0.95,
                        "key_evidence_quote": "Q3 Database migration failed on 2026-07-15",
                    },
                    {
                        "candidate_id": "candidate_2",
                        "relevance_score": 0.05,
                        "directness_score": 0.00,
                        "key_evidence_quote": None,
                    },
                ],
            }
        ),
    },
]
    
    candidate_text: str = build_candidate_text(received_docs)
    
    example_prompt = ChatPromptTemplate.from_messages([
        ("human", "USER QUESTION:\n{question}\n\nCANDIDATE CHUNKS TO EVALUATE:\n{candidate_text}"),
        ("ai", "{output}"),
    ])

    few_shot_prompt = FewShotChatMessagePromptTemplate(
        example_prompt=example_prompt,
        examples=FEW_SHOT_EXAMPLES,
    )

    full_prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_TEMPLATE),
        few_shot_prompt,
        ("human", "USER QUESTION:\n{question}\n\nCANDIDATE CHUNKS TO EVALUATE:\n{candidate_text}"),
    ]).partial(format_instructions=parser.get_format_instructions())
    
    raw_response = None
    extracted_parsed = None

    try:
        log_state(ProviderLog.AI_PROVIDER_REQUEST, function="re_rank_docs", user_id=user_id) 
        log_state(ProviderLog.AI_PROVIDER_IN_PROCESSING, function="re_rank_docs", user_id=user_id)
        
        raw_response = await (full_prompt | model).ainvoke({"question": question, "candidate_text": candidate_text})
        cleaned_content = raw_response.content.strip()
        if cleaned_content.startswith("```"):
            cleaned_content = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned_content)
            cleaned_content = re.sub(r"\n?```$", "", cleaned_content).strip()

        extracted_parsed = parser.parse(cleaned_content)
        
        log_state(ProviderLog.AI_PROVIDER_SUCCESS, level=LogState.INFO, function="re_rank_docs", user_id=user_id)

    except Exception as e:
        if check_provider_quota(e):
            log_state(ProviderLog.AI_PROVIDER_FAILURE, level=LogState.EXCEPTION, function="re_rank_docs", exc=e, user_id=user_id)
            log_state(ServiceLog.AI_SERVICE_FAILED, function="re_rank_docs", user_id=user_id)
            log_state(ServiceLog.EXITING_AI_SERVICE, function="re_rank_docs", user_id=user_id)          
            
            return APIResponse(
                success=False,
                data=None,
                error_code=SYSTEM_ERROR_CODES.MY_QUOTA_REACHED.value,
                error_message="No more tokens left to process this request"
            )
        else:
            log_state(ProviderLog.AI_PROVIDER_FAILURE, level=LogState.EXCEPTION, function="re_rank_docs", exc=e, user_id=user_id)
            log_state(ServiceLog.AI_SERVICE_FAILED, function="re_rank_docs", user_id=user_id)
            log_state(ServiceLog.EXITING_AI_SERVICE, function="re_rank_docs", user_id=user_id)   
            
            extracted_parsed = None
    
    if extracted_parsed and validate_rerank_result(result=extracted_parsed, received_docs=received_docs, user_id=user_id):
        
        final_docs = map_rerank_result_to_docs(extracted_parsed, received_docs, top_k, user_id=user_id)
        if final_docs is not None:
            log_state(ServiceLog.AI_SERVICE_COMPLETED, function="re_rank_docs", user_id=user_id)
            log_state(ServiceLog.AI_SERVICE_ENDED, function="re_rank_docs", user_id=user_id)
            log_state(ServiceLog.EXITING_AI_SERVICE, function="re_rank_docs", user_id=user_id)
            return APIResponse(
                success=True,
                data=final_docs,
                error_code=None,
                error_message=None
            )

    log_state(RepairLog.AI_REPAIR_INITIALIZED, function="re_rank_docs", user_id=user_id)

    raw = getattr(raw_response, "content", None) if raw_response else None

    if raw is None:
        log_state(ServiceLog.AI_SERVICE_FAILED, function="re_rank_docs", level=LogState.WARNING, user_id=user_id)
        log_state(RepairLog.AI_REPAIR_INITIALIZATION_STOPPED, function="re_rank_docs", level=LogState.WARNING, user_id=user_id)
        log_state(ServiceLog.EXITING_AI_SERVICE, function="re_rank_docs", level=LogState.WARNING, user_id=user_id)

        return APIResponse(
            success=False,
            data=None,
            error_code=SYSTEM_ERROR_CODES.AI_SERVICE_FAILURE.value,
            error_message="Structured output parsing failed and manual raw payload was empty"
        )
    
    try:
        log_state(RepairLog.AI_REPAIR_STARTED, function="re_rank_docs", user_id=user_id)  
        log_state(RepairLog.AI_REPAIR_IN_PROGRESS, function="re_rank_docs", user_id=user_id) 
        recovered: RerankResult | None = await extract_raw_data(raw, parser, model, question, RerankResult)
        
    except Exception as e:
        if check_provider_quota(e):
            log_state(ServiceLog.AI_MY_QUOTA_REACHED, level=LogState.EXCEPTION, function="re_rank_docs", exc=e, user_id=user_id)
            log_state(RepairLog.AI_REPAIR_PREMATURELY_ENDED, function="re_rank_docs", user_id=user_id)    
            log_state(ServiceLog.AI_SERVICE_FAILED, function="re_rank_docs", user_id=user_id)
            log_state(ServiceLog.EXITING_AI_SERVICE, function="re_rank_docs", user_id=user_id)    
            
            return APIResponse(
                success=False,
                data=None,
                error_code=SYSTEM_ERROR_CODES.MY_QUOTA_REACHED.value,
                error_message="No more tokens left to process this request"
            )
        else:
            log_state(RepairLog.AI_REPAIR_PREMATURELY_ENDED, level=LogState.EXCEPTION, function="re_rank_docs", exc=e, user_id=user_id)
            log_state(ServiceLog.AI_SERVICE_FAILED, function="re_rank_docs", user_id=user_id)
            log_state(ServiceLog.EXITING_AI_SERVICE, function="re_rank_docs", user_id=user_id)          
            
            raise AIServiceException( 
                error_code=SYSTEM_ERROR_CODES.AI_SERVICE_FAILURE.value,
                message="AI output recovery process failed"
                ) from e
        
    if recovered is None or not validate_rerank_result(recovered, received_docs, user_id=user_id):
        log_state(RepairLog.AI_REPAIR_FAILED, function="re_rank_docs", user_id=user_id)
        log_state(ServiceLog.AI_SERVICE_FAILED, function="re_rank_docs", user_id=user_id)
        log_state(ServiceLog.EXITING_AI_SERVICE, function="re_rank_docs", user_id=user_id)  
        
        return APIResponse(
            success=False,
            data=None,
            error_code=SYSTEM_ERROR_CODES.RAW_REPAIR_FAILURE.value,
            error_message="Structured output parsing failed and manual recovery returned no result."
        )
    
    final_docs = map_rerank_result_to_docs(recovered, received_docs, top_k, user_id=user_id) 
    if final_docs is None:
        log_state(RepairLog.AI_REPAIR_FAILED, function="re_rank_docs", user_id=user_id)
        log_state(ServiceLog.AI_SERVICE_FAILED, function="re_rank_docs", user_id=user_id)
        log_state(ServiceLog.EXITING_AI_SERVICE, function="re_rank_docs", user_id=user_id)  
        return APIResponse(
            success=False,
            data=None,
            error_code=SYSTEM_ERROR_CODES.AI_SERVICE_FAILURE.value,
            error_message="AI rerank result was recovered but document mapping failed."
        )
    log_state(RepairLog.AI_REPAIR_SUCCESS, function="re_rank_docs", user_id=user_id)
    log_state(ServiceLog.AI_SERVICE_COMPLETED, function="re_rank_docs", user_id=user_id)
    log_state(ServiceLog.AI_SERVICE_ENDED, function="re_rank_docs", user_id=user_id)
    log_state(ServiceLog.EXITING_AI_SERVICE, function="re_rank_docs", user_id=user_id)
    
    return APIResponse(
        success=True,
        data=final_docs,
        error_code=None,
        error_message=None
    )