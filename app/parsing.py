"""PDF text → articles → chunks. Pure functions only: no network or database access, so each step is testable on its own.

Pipeline:
    iter_lines      clean each page's text and drop page numbers and running headers
    split_sections  group lines into articles by their article number
    chunk_section   split over-long articles into chunks, tagged with page and citation
"""

import re
from bisect import bisect_right
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.corpus import DocSpec

_FULLWIDTH = str.maketrans(
    {chr(c): chr(c - 0xFEE0) for r in ((0xFF10, 0xFF1A), (0xFF21, 0xFF3B), (0xFF41, 0xFF5B)) for c in range(*r)}
)
_CJK = r"\u3001-\u303f\u4e00-\u9fff\uff01-\uffef"
_SPACE_BETWEEN_CJK = re.compile(rf"(?<=[{_CJK}])\s+(?=[{_CJK}])")
# A line starting with one of these is a new list item and is not joined to the previous line.
_ITEM_START = re.compile(r"[(（【①-⑳—]|\d+[、.]|\d+-\d+、|第\s*\d+\s*條")


@dataclass(frozen=True)
class Line:
    text: str
    pdf_page: int  # position in the PDF file (used for #page= links)
    page: int  # printed page number (shown in citations)
    context: str = ""  # running header or chapter title


@dataclass
class Section:
    label: str
    title: str
    lines: list[Line] = field(default_factory=list)


def clean_line(text: str) -> str:
    """Strip Word layout noise: full-width alphanumerics, spaces between CJK characters, extra whitespace."""
    text = text.replace("\uf095", "~").translate(_FULLWIDTH)
    text = _SPACE_BETWEEN_CJK.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def iter_lines(pages: Iterable[str], spec: DocSpec) -> Iterator[Line]:
    for pdf_page, raw in enumerate(pages, start=1):
        lines = [line for line in map(clean_line, raw.splitlines()) if line]
        if not lines or not (number := spec.page_no.fullmatch(lines[0])):
            continue
        body = lines[1:]
        header = ""
        if spec.running_header and body:
            header, body = body[0], body[1:]
        for text in body:
            yield Line(text, pdf_page, int(number[1]), header)


def split_sections(lines: Iterable[Line], spec: DocSpec) -> list[Section]:
    sections: list[Section] = []
    chapter = ""
    last_number = 0.0
    for line in lines:
        if spec.chapter and spec.chapter.fullmatch(line.text):
            # A chapter title also opens a section, to hold any text between it and the first numbered article.
            chapter = line.text
            sections.append(Section(chapter, ""))
        elif match := spec.heading.match(line.text):
            groups = match.groupdict()
            if groups.get("term"):
                label, title = groups["term"].strip(), groups["zh"].strip()
            else:
                label = groups["label"].replace(" ", "")
                title = (groups.get("title") or "").strip()
            is_new = True
            if spec.ascending and re.fullmatch(r"\d\.\d\d", label):
                is_new = float(label) > last_number
                last_number = max(last_number, float(label))
            if is_new:
                # Articles without a separate title (e.g. 1.01) have body text on the heading line; don't treat it as a title.
                is_sentence = len(title) > 60 or "，" in title or title.endswith("。")
                sections.append(Section(label, "" if is_sentence else title))
        if sections:
            sections[-1].lines.append(Line(line.text, line.pdf_page, line.page, chapter or line.context))
    return sections


def join_lines(lines: list[Line]) -> tuple[str, list[int]]:
    """Rejoin the PDF's hard line breaks into paragraphs; also return each line's start offset in the result."""
    parts: list[str] = []
    offsets: list[int] = []
    length = 0
    for i, line in enumerate(lines):
        if i > 0:
            separator = "\n" if _ITEM_START.match(line.text) or lines[i - 1].text.endswith(("。", "：", ":")) else ""
            parts.append(separator)
            length += len(separator)
        offsets.append(length)
        parts.append(line.text)
        length += len(line.text)
    return "".join(parts), offsets


def chunk_section(section: Section, spec: DocSpec, splitter: RecursiveCharacterTextSplitter) -> list[Document]:
    text, offsets = join_lines(section.lines)
    # Don't index sections that are a heading with no body (e.g. the chapter line "5.00 比賽之進行").
    if len(text) - len(section.lines[0].text) < 15:
        return []
    name = f"{section.label} {section.title}".strip()
    documents = []
    for piece in splitter.create_documents([text]):
        start = section.lines[bisect_right(offsets, piece.metadata["start_index"]) - 1]
        # Prepend the citation to the chunk so both the embedding and the LLM see which article the text belongs to.
        header = f"《{spec.title}》{name}"
        if start.context and start.context != section.label:
            header += f"｜{start.context}"
        documents.append(
            Document(
                page_content=f"{header}\n{piece.page_content}",
                metadata={
                    "doc": spec.key,
                    "doc_title": spec.title,
                    "section": section.label,
                    "title": section.title,
                    "context": start.context,
                    "page": start.page,
                    "url": f"{spec.url}#page={start.pdf_page}",
                },
            )
        )
    return documents


def make_splitter(chunk_size: int, chunk_overlap: int) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n", "。", ""],
        keep_separator="end",
        add_start_index=True,
    )


def parse_document(pages: Iterable[str], spec: DocSpec, splitter: RecursiveCharacterTextSplitter) -> list[Document]:
    sections = split_sections(iter_lines(pages, spec), spec)
    return [doc for section in sections for doc in chunk_section(section, spec, splitter)]
