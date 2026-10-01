"""Corpus definition: the three official CPBL PDFs and the layout rules of each.

Page numbers, running headers and article numbering differ per document. DocSpec
captures those differences so the splitting logic in parsing.py is shared.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import httpx

BASE_URL = "https://www.cpbl.com.tw"


@dataclass(frozen=True)
class DocSpec:
    key: str
    title: str
    url: str
    # Printed page number on the first line of a page. Pages without one (cover, TOC, colophon) are skipped.
    page_no: re.Pattern[str]
    # Article heading line. Named groups: label (article number), title (optional).
    heading: re.Pattern[str]
    # Whether the line after the page number is a running header (e.g. "5.06(b) 跑壘員與擊球員安全進壘").
    running_header: bool = False
    # Chapter title line in the body (how documents without running headers get their chapter name).
    chapter: re.Pattern[str] | None = None
    # Whether article numbers increase through the whole document. Rejects body lines
    # that merely happen to start with an article number after a line wrap.
    ascending: bool = False

    @property
    def filename(self) -> str:
        return f"{self.key}.pdf"


DOCS = [
    DocSpec(
        key="rules",
        title="棒球規則",
        url=f"{BASE_URL}/files/file_pool/1/0q098634730686681733/%e6%a3%92%e7%90%83%e8%a6%8f%e5%89%87.pdf",
        page_no=re.compile(r"-(\d+)-"),
        # Two heading forms: "5.07 投球 Pitching", and "INFIELD FLY 內野飛球—" in the definitions chapter.
        heading=re.compile(
            r"(?P<label>\d\.\d\d)\s+(?P<title>\S.*)"
            r"|(?P<term>[A-Z]{2,}[A-Za-z'’ .\-()]*?)\s*(?P<zh>[\u4e00-\u9fff][^—|]*)[—|]"
        ),
        running_header=True,
        ascending=True,
    ),
    DocSpec(
        key="supplement",
        title="裁判執法手冊規則補述",
        url=f"{BASE_URL}/theme/client/download/%e8%a3%81%e5%88%a4%e5%9f%b7%e6%b3%95%e6%89%8b%e5%86%8a%e8%a6%8f%e5%89%87%e8%a3%9c%e8%bf%b0.pdf",
        page_no=re.compile(r"-(\d+)-"),
        # Chapter 6 has no article numbers; split it on its two sub-headings (rulings that can /
        # cannot be changed). Otherwise, once the lists are chunked, the two are indistinguishable.
        heading=re.compile(r"(?P<label>\d\.\d\d)\s*【(?P<title>[^】]+)|【(?P<term>不?可更改判決之狀況)】(?P<zh>)$"),
        chapter=re.compile(r"第[一二三四五六七八九十]+章\s*\S.*"),
        ascending=True,
    ),
    DocSpec(
        key="league",
        title="聯盟規章",
        url=f"{BASE_URL}/theme/client/download/%e8%81%af%e7%9b%9f%e8%a6%8f%e7%ab%a0.pdf",
        page_no=re.compile(r"(\d+)"),
        # Appendices restart numbering from 第1條, so ascending can't be used here.
        # An article number followed by 之, 規定, 第… is a reference in body text
        # (e.g. "第 9 條規定辦理"), not a heading.
        heading=re.compile(
            r"(?P<label>第\s*\d+\s*條)(?:\s*[【(（](?P<title>[^】)）]+)[】)）])?"
            r"(?![之規辦第及或所至、，。；－\-）)】])"
        ),
        running_header=True,
    ),
]


def download(data_dir: Path, force: bool = False) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    # The site's CDN sets a cookie and redirects back to the same URL. Use one Client
    # (which keeps cookies) and follow redirects, or the request redirects forever.
    headers = {"User-Agent": "Mozilla/5.0 (cpbl-rules-rag-demo)"}
    with httpx.Client(follow_redirects=True, headers=headers, timeout=60) as client:
        for spec in DOCS:
            path = data_dir / spec.filename
            if path.exists() and not force:
                continue
            response = client.get(spec.url)
            response.raise_for_status()
            if not response.content.startswith(b"%PDF"):
                raise RuntimeError(f"{spec.url} 回傳的不是 PDF，官網連結可能已更換")
            path.write_bytes(response.content)
            print(f"下載 {spec.title} → {path} ({len(response.content) // 1024} KB)")
