"""
Layer 3 — Notes Recall (Streamlit app, deployed version)

Upload documents, paste a claim, get back the most relevant passages.
Uses OpenAI embeddings — fast, no local model download.
Index is session-scoped: lives in memory, cleared when the browser tab closes.

Run locally:
    uv run streamlit run ui/layer3_app.py

Deploy: set OPENAI_API_KEY in Streamlit Cloud secrets.
"""

import io
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
import fitz  # pymupdf
import streamlit as st

# Load .env from repo root for local development
load_dotenv(Path(__file__).parent.parent / ".env")
from docx import Document
from openai import OpenAI

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMBED_MODEL   = "text-embedding-3-small"   # cheap, fast, good enough
CHUNK_SIZE    = 800   # characters — larger chunks = fewer API calls, still fine for retrieval
CHUNK_OVERLAP = 50
TOP_K = 5


# ---------------------------------------------------------------------------
# OpenAI client (cached)
# ---------------------------------------------------------------------------

@st.cache_resource
def get_client() -> OpenAI:
    key = None
    try:
        key = st.secrets["OPENAI_API_KEY"]
    except Exception:
        key = os.getenv("OPENAI_API_KEY")
    if not key:
        st.error("OPENAI_API_KEY not set. Add it in Streamlit Cloud → Settings → Secrets.")
        st.stop()
    return OpenAI(api_key=key)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    text: str
    filename: str
    page: int           # 0 = unknown
    embedding: list[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

MAX_PDF_PAGES = 150   # hard cap — protects Cloud memory limit

def extract_pdf(data: bytes, filename: str) -> list[tuple[str, int]]:
    """Extract text page-by-page using pymupdf (fitz) — lower memory than pdfplumber."""
    pages = []
    try:
        import sys
        print(f"[layer3] opening PDF '{filename}' ({len(data)/1e6:.1f} MB)", flush=True, file=sys.stderr)
        with fitz.open(stream=data, filetype="pdf") as pdf:
            total = len(pdf)
            if total > MAX_PDF_PAGES:
                st.warning(
                    f"'{filename}' has {total} pages — indexing the first {MAX_PDF_PAGES} only. "
                    "Split the file to index the rest."
                )
            for i, page in enumerate(pdf, start=1):
                if i > MAX_PDF_PAGES:
                    break
                try:
                    text = page.get_text() or ""
                except Exception:
                    text = ""
                if text.strip():
                    pages.append((text, i))
    except Exception as e:
        st.warning(f"Could not read PDF '{filename}': {e}. Try saving as a text file instead.")
    return pages


def extract_docx(data: bytes) -> list[tuple[str, int]]:
    try:
        doc = Document(io.BytesIO(data))
        paras = [p.text for p in doc.paragraphs if p.text.strip()]
        return [(p, 0) for p in paras]
    except Exception as e:
        st.warning(f"Could not read .docx file: {e}.")
        return []


def extract_txt(data: bytes) -> list[tuple[str, int]]:
    return [(data.decode("utf-8", errors="replace"), 0)]


MAX_FILE_MB = 20

def extract(uploaded_file) -> list[tuple[str, int]]:
    data = uploaded_file.read()
    mb = len(data) / 1_048_576
    if mb > MAX_FILE_MB:
        st.warning(
            f"'{uploaded_file.name}' is {mb:.1f} MB — limit is {MAX_FILE_MB} MB. "
            "Split into smaller files or export as .txt."
        )
        return []
    suffix = uploaded_file.name.rsplit(".", 1)[-1].lower()
    if suffix == "pdf":
        return extract_pdf(data, uploaded_file.name)
    elif suffix == "docx":
        return extract_docx(data)
    elif suffix in ("txt", "md"):
        return extract_txt(data)
    return []


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            while end < len(text) and not text[end].isspace():
                end += 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
    return chunks


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_chunks(chunks: list[Chunk], client: OpenAI) -> list[Chunk]:
    """Embed all chunks in batches of 512 (API limit is 2048, staying conservative)."""
    batch_size = 512
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        texts = [c.text for c in batch]
        try:
            response = client.embeddings.create(model=EMBED_MODEL, input=texts)
            for chunk, item in zip(batch, response.data):
                chunk.embedding = item.embedding
        except Exception as e:
            st.error(f"Embedding error (batch {i//batch_size + 1}): {e}")
            raise
    return chunks


def embed_query(query: str, client: OpenAI) -> list[float]:
    response = client.embeddings.create(model=EMBED_MODEL, input=[query])
    return response.data[0].embedding


# ---------------------------------------------------------------------------
# Similarity search
# ---------------------------------------------------------------------------

def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def search(query_embedding: list[float], index: list[Chunk], top_k: int = TOP_K) -> list[tuple[Chunk, float]]:
    scored = [(chunk, cosine_similarity(query_embedding, chunk.embedding)) for chunk in index]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------

def get_index() -> list[Chunk]:
    if "index" not in st.session_state:
        st.session_state["index"] = []
    return st.session_state["index"]


def get_indexed_files() -> set[str]:
    if "indexed_files" not in st.session_state:
        st.session_state["indexed_files"] = set()
    return st.session_state["indexed_files"]


# ---------------------------------------------------------------------------
# Streamlit app
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Notes Recall",
    page_icon="🔎",
    layout="wide",
)

st.title("Notes Recall")
st.caption(
    "Upload documents, paste a claim, get back the source passages. "
    "Index lives in your browser session — nothing is stored after you close the tab."
)

try:
    client = get_client()
except Exception as e:
    st.error(f"Failed to initialize OpenAI client: {e}")
    st.stop()
index = get_index()
indexed_files = get_indexed_files()

# --- Sidebar ---
with st.sidebar:
    st.header("Upload documents")

    uploaded = st.file_uploader(
        "Drop files here",
        type=["pdf", "txt", "md", "docx"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )

    if uploaded:
        new_files = [f for f in uploaded if f.name not in indexed_files]
        if new_files:
            progress_label = st.empty()
            progress_bar   = st.progress(0)
            try:
                new_chunks = []
                for fi, f in enumerate(new_files):
                    progress_label.caption(f"Extracting {f.name}…")
                    pages = extract(f)
                    for page_text, page_num in pages:
                        for chunk_text_item in chunk_text(page_text):
                            new_chunks.append(Chunk(
                                text=chunk_text_item,
                                filename=f.name,
                                page=page_num,
                            ))
                    progress_bar.progress((fi + 1) / (len(new_files) + 1))

                if new_chunks:
                    progress_label.caption(f"Embedding {len(new_chunks):,} passages…")
                    embed_chunks(new_chunks, client)
                    index.extend(new_chunks)
                    for f in new_files:
                        indexed_files.add(f.name)
                    st.session_state["index"] = index
                    st.session_state["indexed_files"] = indexed_files

                progress_bar.progress(1.0)
                progress_label.empty()
                progress_bar.empty()
            except Exception as e:
                progress_label.empty()
                progress_bar.empty()
                st.error(f"Indexing failed: {e}")

    if index:
        st.success(f"{len(index):,} passages indexed")
        st.markdown("**Files:**")
        for fname in sorted(indexed_files):
            st.markdown(f"- {fname}")
    else:
        st.info("No documents uploaded yet.")

    if index and st.button("Clear session", use_container_width=True):
        st.session_state["index"] = []
        st.session_state["indexed_files"] = set()
        st.rerun()

    st.divider()
    st.header("About")
    st.markdown(
        "Finds the passages in your documents most likely to be the source of a claim. "
        "Uses semantic similarity — paraphrases and related facts surface, not just exact matches.\n\n"
        "**Supported:** PDF, .txt, .md, .docx\n\n"
        "**Model:** `text-embedding-3-small` (OpenAI)\n\n"
        "**Privacy:** text is sent to OpenAI for embedding only — not stored or used for training."
    )

# --- Main panel ---
st.subheader("Paste a claim")

claim = st.text_area(
    label="Claim",
    label_visibility="collapsed",
    height=100,
    placeholder="e.g. Evictions rose 27% in Los Angeles last year, according to a new report.",
)

search_btn = st.button("Find source passages", type="primary")

if search_btn:
    if not claim.strip():
        st.info("Paste a claim above to search.")
    elif not index:
        st.warning("No documents uploaded yet — add files in the sidebar first.")
    else:
        with st.spinner("Searching…"):
            query_emb = embed_query(claim.strip(), client)
            results = search(query_emb, index)

        st.divider()
        st.subheader(f"Top {len(results)} passages")

        for i, (chunk, score) in enumerate(results, start=1):
            page_label = f" · p. {chunk.page}" if chunk.page else ""
            score_color = "#2d8a4e" if score > 0.6 else "#b45309" if score > 0.4 else "#888"

            col_score, col_body = st.columns([1, 8])
            with col_score:
                st.markdown(
                    f"<div style='text-align:center;padding-top:6px'>"
                    f"<span style='font-size:20px;font-weight:bold;color:{score_color}'>"
                    f"{score:.0%}</span><br>"
                    f"<span style='font-size:10px;color:#aaa'>match</span></div>",
                    unsafe_allow_html=True,
                )
            with col_body:
                st.markdown(
                    f"**{chunk.filename}**{page_label}",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<div style='font-family:serif;font-size:14px;line-height:1.7;"
                    f"padding:10px 14px;background:#f9f9f9;border-left:3px solid #ddd;"
                    f"border-radius:2px;margin-top:4px'>{chunk.text}</div>",
                    unsafe_allow_html=True,
                )

            if i < len(results):
                st.divider()
