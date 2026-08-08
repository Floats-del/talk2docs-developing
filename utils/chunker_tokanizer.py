from utils.config import Settings
from langchain_huggingface import HuggingFaceEmbeddings
from transformers import AutoTokenizer
from docling.chunking import HybridChunker


max_tokens = Settings.tokenizer_max_tokens
model_id = Settings.tokenizer
tokenizer_ = AutoTokenizer.from_pretrained(model_id)
embedding_model = HuggingFaceEmbeddings(
    model_name=Settings.embedding_model
)


chunker = (
    HybridChunker(  # internally chunks on the basises of similarity of next sentence with another so, onece a new convo starts thats where its gon chunk
        # assuming last convo finished roughlysepaking actual is more robust and has overlap internally so dont even wory!
        tokenizer=tokenizer_,
        max_tokens=max_tokens,  # useally enough to preserve context
        merge_peers=True,  # Merge small adjacent chunks
    )
)