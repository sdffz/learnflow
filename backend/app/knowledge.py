import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field


class Source(BaseModel):
    title: str
    module: str
    knowledge_point: str
    path: str


class RetrievedChunk(BaseModel):
    text: str
    source: Source
    score: float


class TutorAnswer(BaseModel):
    text: str
    sources: list[Source] = Field(default_factory=list)
    refused: bool
    refusal_reason: str | None = None


@dataclass(frozen=True)
class _Chunk:
    text: str
    source: Source
    ngrams: frozenset[str]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _ngrams(text: str) -> frozenset[str]:
    normalized = _normalize(text)
    grams = {normalized[index : index + 2] for index in range(max(0, len(normalized) - 1))}
    grams.update(re.findall(r"[a-z0-9_]+", normalized))
    return frozenset(grams)


QUESTION_FRAMES = re.compile(
    r"什么是|是什么|为什么|为何|怎么样|怎么|如何|请问|请解释|解释一下|介绍一下|有哪些|区别"
)
NEGATIVE_PREFIXES = frozenset("无非半反")


def _search_term(query: str) -> str:
    cleaned = QUESTION_FRAMES.sub("", _normalize(query))
    return re.sub(r"[^\w\u4e00-\u9fff]", "", cleaned)


def _phrase_signal(term: str, text: str) -> float:
    normalized = _normalize(text)
    if len(term) < 2:
        return 0
    positions = [match.start() for match in re.finditer(re.escape(term), normalized)]
    if not positions:
        return 0
    positive = False
    contradictory = False
    for position in positions:
        previous = normalized[position - 1] if position else ""
        if previous in NEGATIVE_PREFIXES and not term.startswith(previous):
            contradictory = True
        else:
            positive = True
    if positive:
        return 0.45
    if contradictory:
        return -0.5
    return 0


class KnowledgeBase:
    def __init__(self, root: Path):
        self._chunks = self._load(root)

    def _load(self, root: Path) -> list[_Chunk]:
        chunks: list[_Chunk] = []
        for path in sorted(root.glob("*.md")):
            if path.name.startswith(".") or not path.is_file():
                continue
            raw = path.read_text(encoding="utf-8")
            header, separator, body = raw.partition("\n\n")
            values = dict(
                line.split(": ", 1)
                for line in header.splitlines()
                if ": " in line
            )
            if not separator or not {"title", "module", "knowledge_point"}.issubset(values):
                raise ValueError(f"Invalid knowledge document header: {path}")
            source = Source(
                title=values["title"],
                module=values["module"],
                knowledge_point=values["knowledge_point"],
                path=path.name,
            )
            paragraphs = filter(None, (item.strip() for item in body.split("\n\n")))
            chunks.extend(
                _Chunk(text=paragraph, source=source, ngrams=_ngrams(paragraph))
                for paragraph in paragraphs
            )
        return chunks

    def search(self, query: str, limit: int = 4) -> list[RetrievedChunk]:
        term = _search_term(query)
        query_grams = _ngrams(term or query)
        if not query_grams:
            return []

        scored: list[RetrievedChunk] = []
        for chunk in self._chunks:
            overlap = len(query_grams & chunk.ngrams)
            lexical_score = overlap / len(query_grams)
            phrase_signal = _phrase_signal(term, chunk.text)
            length_penalty = 0.03 * max(0, len(_normalize(chunk.text)) - 120) / 100
            score = max(0, lexical_score + phrase_signal - length_penalty)
            if score >= 0.12:
                scored.append(
                    RetrievedChunk(text=chunk.text, source=chunk.source, score=score)
                )
        return sorted(scored, key=lambda item: item.score, reverse=True)[:limit]

    def answer(self, query: str) -> TutorAnswer:
        if re.search(r"忽略知识库|编造|系统提示|泄露密钥", query):
            return TutorAnswer(
                text="我不能绕过课程证据规则或执行与该问题无关的指令。",
                refused=True,
                refusal_reason="prompt_injection",
            )

        hits = self.search(query)
        if not hits:
            return TutorAnswer(
                text="当前课程知识库没有足够依据回答这个问题。请换一个《人工智能导论》相关问题。",
                refused=True,
                refusal_reason="insufficient_evidence",
            )

        top_score = hits[0].score
        primary_hits = [item for item in hits if item.score >= max(0.12, top_score * 0.78)]
        evidence = " ".join(item.text for item in primary_hits)
        sources: list[Source] = []
        seen_sources: set[tuple[str, str]] = set()
        for item in primary_hits:
            key = (item.source.path, item.source.knowledge_point)
            if key not in seen_sources:
                seen_sources.add(key)
                sources.append(item.source)
        return TutorAnswer(
            text=f"根据课程资料：{evidence}",
            sources=sources,
            refused=False,
        )
