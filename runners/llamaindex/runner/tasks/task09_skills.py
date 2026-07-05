"""Demo #9 — LlamaIndex handler: naive (prompt-stuff) + RAG arms of the Skills demo.

The naive arm stuffs the entire knowledge corpus into the system prompt (the
strategy Colmena's load_skill is designed to beat). The RAG arm is the steelman
competitor: it embeds the corpus into an in-memory vector index (embeddings
routed through the proxy) and retrieves only the top-k chunks for the question.

Tokens are measured by the driver from proxy spans; usage is returned as zeros.
Arms other than naive/rag raise ValueError.
"""
from __future__ import annotations

import os
from typing import Any

from llama_index.core.llms import ChatMessage, MessageRole

from bench_common import RunnerArgs
from bench_common import rag_index as ri
from bench_common import scenario_skills as sk


def _ask_llm(llm: Any, system: str, user: str) -> str:
    # Plain system+user chat through the proxy-wired OpenAILike client (mirror
    # task01/task08 wiring — the `llm` arg is already pointed at the proxy).
    messages = [
        ChatMessage(role=MessageRole.SYSTEM, content=system),
        ChatMessage(role=MessageRole.USER, content=user),
    ]
    resp = llm.chat(messages)
    return resp.message.content if hasattr(resp, "message") else str(resp)


def _run_rag(llm: Any, args: RunnerArgs, skills_dir: str, question) -> tuple[str, dict[str, Any]]:
    from llama_index.core import Document, VectorStoreIndex
    from llama_index.embeddings.openai import OpenAIEmbedding

    chunks = ri.chunk_corpus(skills_dir)
    # Decision B fallback: the LiteLLM proxy /embeddings route fails with
    # "No connected db" (litellm requires a DB for embeddings even with a
    # configured model). Route embeddings DIRECTLY to OpenAI so RAG actually
    # retrieves; the completion call below stays on the proxy-wired `llm`.
    embed = OpenAIEmbedding(
        model=os.environ.get("BENCH_EMBED_MODEL", "text-embedding-3-small"),
        api_key=os.environ["OPENAI_API_KEY"],
        api_base="https://api.openai.com/v1",   # explicit: override .env OPENAI_BASE_URL (=proxy)
        max_retries=8,   # embeddings API 429s under the 50-pack sweep; back off instead of failing the run
    )
    docs = [
        Document(
            text=c["text"],
            metadata={"pack": c["pack"], "relpath": c["relpath"]},
            excluded_embed_metadata_keys=["pack", "relpath"],
            excluded_llm_metadata_keys=["pack", "relpath"],
        )
        for c in chunks
    ]
    index = VectorStoreIndex.from_documents(docs, embed_model=embed)
    retriever = index.as_retriever(similarity_top_k=4)
    nodes = retriever.retrieve(question.text)

    retrieved = [
        {"pack": n.metadata.get("pack"), "relpath": n.metadata.get("relpath")}
        for n in nodes
    ]
    hit = ri.correct_chunk_hit(question, retrieved)

    excerpts = "\n\n".join(n.get_content() for n in nodes)
    system = (
        "You are a finance analyst. Use ONLY the retrieved policy excerpts to "
        "answer. Return only the final number."
    )
    user = excerpts + "\n\nQuestion: " + question.text
    answer = _ask_llm(llm, system, user)
    embed_chars = sum(len(c["text"]) for c in chunks)
    extras = {
        "retrieval_hit": hit,
        "retrieved_count": len(retrieved),
        "embed_provider": "openai-direct",
        "embed_chars": embed_chars,
    }
    return str(answer), extras


def run(
    task_def: dict[str, Any], llm: Any, args: RunnerArgs
) -> tuple[Any, dict[str, int], dict[str, Any]]:
    arm = os.environ.get("BENCH_SKILLS_ARM", "naive")
    skills_dir = os.environ["BENCH_SKILLS_DIR"]
    qid = os.environ["BENCH_QUESTION_ID"]
    question = next(q for q in sk.QUESTION_BANK if q.id == qid)

    if arm == "naive":
        system = sk.build_naive_system_prompt(skills_dir)
        answer = _ask_llm(llm, system, question.text)
        usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
        extras = {"arm": arm, "question_id": qid}
        return str(answer), usage, extras

    if arm == "rag":
        answer, rag_extras = _run_rag(llm, args, skills_dir, question)
        usage = {"input": 0, "output": 0, "cached": 0, "tool_calls": 0}
        extras = {"arm": arm, "question_id": qid, **rag_extras}
        return answer, usage, extras

    raise ValueError(f"arm {arm!r} not supported")
