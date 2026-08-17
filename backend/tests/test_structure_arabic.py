"""结构重建：阿拉伯数字章/节标题识别 + hash 兜底防退化。

验证修复（2026-08-09）：
- RE_CH_LEVEL1 / RE_LEVEL2_JIE 支持阿拉伯数字 + 带空格变体
- hash 兜底 toc 白名单为空时不启用（宁 0 章不切片）
- cn_to_int 支持阿拉伯数字
"""
from app.services import structure


# ── 辅助 ──────────────────────────────────────────────

def _rebuild(text: str) -> dict:
    batches = [{"idx": 1, "page_start": 1, "page_end": 99, "text": text, "content_list": None}]
    return structure.rebuild_v2(batches)


def _chapter_titles(result: dict) -> list[str]:
    return [ch["title"] for ch in result["chapters"]]


# ── 阿拉伯数字章 ─────────────────────────────────────

def test_arabic_chapter_detected():
    """第1章/第 3 章/第 11 章 被识别为章标题。"""
    text = "# 第1章 绪论\n正文\n# 第 3 章 组织学\n正文\n# 第 11 章 药物学基础\n正文"
    result = _rebuild(text)
    titles = _chapter_titles(result)
    assert "第1章 绪论" in titles
    assert "第 3 章 组织学" in titles
    assert "第 11 章 药物学基础" in titles
    assert len(titles) == 3


def test_arabic_section_detected():
    """第1节/第 2 节 被识别为节标题（level 2 children）。"""
    text = "# 第1章 人体解剖学\n# 第1节 运动系统\n内容\n# 第 2 节 内脏学\n内容"
    result = _rebuild(text)
    assert len(result["chapters"]) == 1
    ch = result["chapters"][0]
    assert len(ch["children"]) == 2
    assert ch["children"][0]["title"] == "第1节 运动系统"
    assert ch["children"][1]["title"] == "第 2 节 内脏学"


def test_arabic_level3_paren():
    """(1) / （ 2 ） 识别为三级标题。"""
    text = "# 第1章 概论\n# 第1节 内容\n## (1) 子标题\n正文\n## （ 2 ）另一个\n正文"
    result = _rebuild(text)
    ch = result["chapters"][0]
    # P0-2 真树化后：节标题是章的 children，三级标题是节的 children
    section = ch["children"][0]
    level3 = [c for c in section["children"] if c["level"] == 3]
    assert len(level3) == 2
    assert level3[0]["title"] == "(1) 子标题"
    assert level3[1]["title"] == "（ 2 ）另一个"


# ── 案例/问题框不切章 ─────────────────────────────────

def test_case_box_not_chapter():
    """案例2-1/问题 不能成为章，应并入当前章内容。"""
    text = (
        "# 第1章 绪论\n基础内容\n"
        "# 案例2-1\n患者35岁…\n"
        "# 问题\n1. 什么是…\n"
        "# 第2章 生理学\n正文"
    )
    result = _rebuild(text)
    titles = _chapter_titles(result)
    assert "案例2-1" not in titles
    assert "问题" not in titles
    assert len(titles) == 2  # 只有第1章、第2章


def test_short_text_not_chapter():
    """纯文本短行（生理性抗凝物质/按心力衰竭发生的部位分为：）不切章。"""
    text = (
        "# 第1章 概论\n# 第1节 内容\n"
        "# 生理性抗凝物质\n正文\n"
        "# 按心力衰竭发生的部位分为：\n正文\n"
        "# 第2章 结论\n正文"
    )
    result = _rebuild(text)
    titles = _chapter_titles(result)
    assert "生理性抗凝物质" not in titles
    assert "按心力衰竭发生的部位分为：" not in titles
    assert len(titles) == 2


# ── hash 兜底防退化 ────────────────────────────────────

def test_hash_disabled_when_toc_empty():
    """无目录页 + 无编号（numbered=0）→ hash 兜底不启用 → 0 章而非全切片。"""
    # 模拟无编号教材：所有标题都是 # 行但无「第x章」格式
    text = "# 概论\n正文\n# 学习目标\n内容\n# 第一部分\n正文"
    result = _rebuild(text)
    # numbered=0 且 toc_titles 为空 → hash 兜底不启用 → 0 章
    assert len(result["chapters"]) == 0


# ── cn_to_int 阿拉伯数字 ──────────────────────────────

def test_cn_to_int_arabic():
    assert structure.cn_to_int("1") == 1
    assert structure.cn_to_int("11") == 11
    assert structure.cn_to_int(" 3 ") == 3
    # 中文数字仍然支持
    assert structure.cn_to_int("一") == 1
    assert structure.cn_to_int("十一") == 11


# ── 中文数字章仍正常 ──────────────────────────────────

def test_cn_chapter_still_works():
    """第一章/第二节 中文数字格式仍然正常识别。"""
    text = "# 第一章 管理与管理\n# 第一节 概述\n正文\n# 第二章 历史\n正文"
    result = _rebuild(text)
    assert len(result["chapters"]) == 2
    assert result["chapters"][0]["children"][0]["title"] == "第一节 概述"



# ── P0-1 目录行过滤放宽（2026-08-15）──────────────────

def test_toc_line_no_dots_filtered():
    """无点线目录行（只有页码）也应被过滤，不进入章节树。"""
    text = "# 第1章 绪论\n正文\n第一章 事件与概率 1\n第二章 随机变量 3"
    result = _rebuild(text)
    assert _chapter_titles(result) == ["第1章 绪论"]


def test_toc_line_paren_page_filtered():
    """带括号页码的阿拉伯数字节目录行应被过滤，不成为节标题。"""
    text = "# 第1章 绪论\n正文\n1.1 药物的质量评价 (1)\n1.2 药物分析 (2)"
    result = _rebuild(text)
    ch = result["chapters"][0]
    assert ch["children"] == []
    assert "正文" in ch["lines"]


def test_toc_line_old_dots_still_filtered():
    """旧版点线目录行仍然被过滤。"""
    text = "# 第一章 管理\n正文\n第二章 组织 …… 12"
    result = _rebuild(text)
    assert _chapter_titles(result) == ["第一章 管理"]


def test_toc_batch_ratio_skip_whole_batch():
    """目录行占比 >50% 的批次整批降权，不参与标题识别。"""
    text = "\n".join([
        "第一章 事件与概率 1",
        "第二章 随机变量 3",
        "第三章 分布 5",
    ])
    batches = [{"idx": 1, "page_start": 1, "page_end": 3, "text": text, "content_list": None}]
    result = structure.rebuild(batches)
    assert result["chapters"] == []


# ── P0-2 标题评分制 + 真树化（2026-08-15）────────────────

def test_plain_cn_dot_line_not_heading_without_hash_or_toc():
    """正文中的“一、”行：无 # 且无目录白名单时不当标题，归入正文。"""
    text = "# 第1章 绪论\n正文开头\n一、这是正文内容不是标题\n继续"
    result = _rebuild(text)
    ch = result["chapters"][0]
    assert ch["children"] == []
    assert any("一、这是正文内容不是标题" in l for l in ch["lines"])


def test_nested_tree_structure():
    """真树化：节 → 小节 → 次小节 嵌套在 children 中。"""
    text = (
        "# 第1章 概论\n"
        "# 第1节 内容\n"
        "## 一、概述\n"
        "### （一）背景\n"
        "正文"
    )
    result = _rebuild(text)
    ch = result["chapters"][0]
    assert ch["children"][0]["title"] == "第1节 内容"
    assert ch["children"][0]["children"][0]["title"] == "一、概述"
    assert ch["children"][0]["children"][0]["children"][0]["title"] == "（一）背景"