from app.corpus import DOCS
from app.parsing import clean_line, iter_lines, join_lines, make_splitter, parse_document, split_sections

RULES, SUPPLEMENT, LEAGUE = DOCS


def test_clean_line_removes_layout_noise():
    assert clean_line("  第４５條  【即時 重播】 總 教練  ") == "第45條【即時重播】總教練"
    assert clean_line("進 1 個壘") == "進 1 個壘"


def test_pages_without_page_number_are_skipped():
    pages = ["目 錄\n5.07 投球．．．．68", "-1-\n比賽之目的 1.01~1.06\n1.01 棒球運動是比賽。"]
    lines = list(iter_lines(pages, RULES))
    assert [(line.text, line.pdf_page, line.page, line.context) for line in lines] == [
        ("1.01 棒球運動是比賽。", 2, 1, "比賽之目的 1.01~1.06")
    ]


def test_rules_split_by_rule_number_and_definition_term():
    pages = [
        "-40-\n投球 5.07\n5.07 投 球 Pitching\n投手應採用合法姿勢。\n參照\n5.06 之規定辦理。",
        "-197-\n定義 I\nINFIELD FLY 內野飛球—無出局或一出局時之界內飛球。",
    ]
    sections = split_sections(iter_lines(pages, RULES), RULES)
    # "5.06 之規定辦理" is body text that happens to start with an article number after a line wrap;
    # the number doesn't increase, so it isn't a new article.
    assert [(s.label, s.title) for s in sections] == [("5.07", "投球 Pitching"), ("INFIELD FLY", "內野飛球")]
    assert len(sections[0].lines) == 4


def test_league_reference_is_not_a_heading():
    pages = ["36\n第9 章 聯盟競賽規程\n第45條【即時重播輔助判決】總教練得提出挑戰。\n依\n第 9 條規定辦理。"]
    sections = split_sections(iter_lines(pages, LEAGUE), LEAGUE)
    assert [(s.label, s.title) for s in sections] == [("第45條", "即時重播輔助判決")]


def test_supplement_chapter_without_numbered_articles():
    pages = [
        "-90-\n第六章裁決結果是否可更判之規定\n概要說明：裁判員之宣判即為最後判決。\n【不可更改判決之狀況】\n(1) 好球或壞球。"
    ]
    sections = split_sections(iter_lines(pages, SUPPLEMENT), SUPPLEMENT)
    assert [s.label for s in sections] == ["第六章裁決結果是否可更判之規定", "不可更改判決之狀況"]


def test_join_lines_restores_paragraphs():
    lines = list(iter_lines(["-1-\n頁眉\n投手應在\n時限內投球。\n（a）壘上無人\n時為 18 秒"], RULES))
    text, offsets = join_lines(lines)
    assert text == "投手應在時限內投球。\n（a）壘上無人時為 18 秒"
    assert offsets == [0, 4, 11, 18]


def test_chunks_carry_citation_metadata():
    body = "。".join(f"第 {i} 種情形時跑壘員出局" for i in range(60))
    pages = [f"-58-\n5.09(b) 跑壘員出局\n5.09 出 局 Making an Out\n{body}", f"-59-\n跑壘員出局 5.09(b)\n{body}"]
    chunks = parse_document(pages, RULES, make_splitter(300, 30))
    assert len(chunks) > 2
    assert chunks[0].page_content.startswith("《棒球規則》5.09 出局 Making an Out｜5.09(b) 跑壘員出局\n")
    assert chunks[0].metadata["page"] == 58
    assert chunks[-1].metadata["page"] == 59
    assert chunks[-1].metadata["url"].endswith("#page=2")
