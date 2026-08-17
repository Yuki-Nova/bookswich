"""目录驱动重建测试（2026-08-16 P0-5）：教材目录 → 章节白名单 + 区域跳过。

背景问题（真实数据 b8_工业药剂学）：目录页的「第x章」目录行页码被 OCR 丢失
（行尾无数字）→ _is_toc_line 失效 → 目录残渣被识别成假章节，与正文真章重复。

方案：
- extract_toc_entries：从「## 目录」锚点后提取目录条目（页码容忍丢失）
- rebuild_v2 集成：目录区域整段跳过；正文「第x章」必须命中目录白名单
  并按目录顺序推进；目录不可用（提取为空）时完全回退原逻辑
"""
from app.services import structure


def _rebuild(text: str) -> dict:
    batches = [{"idx": 1, "page_start": 1, "page_end": 99, "text": text, "content_list": None}]
    return structure.rebuild_v2(batches)


def _titles(result: dict) -> list[str]:
    return [ch["title"] for ch in result["chapters"]]


# ── 目录条目提取 ─────────────────────────────────────


def test_extract_toc_entries_basic():
    """目录锚点后的 第x章 行被提取（页码可有可无，标题去除编号）。"""
    text = (
        "封面文本\n"
        "## 目录\n"
        "第一章 绪论  \n"
        "第二章 药物制剂的设计与质量控制  \n"
        "第四章 药物制剂的稳定性  76\n"
        "第五章 制剂车间设计概述……101\n"
        "# 第一章 绪论\n正文\n"
    )
    batches = [{"idx": 1, "page_start": 1, "page_end": 99, "text": text, "content_list": None}]
    entries = structure.extract_toc_entries(batches)
    assert len(entries) == 4
    assert entries[0] == {"no": 1, "title": "绪论", "page": None}
    assert entries[1] == {"no": 2, "title": "药物制剂的设计与质量控制", "page": None}
    assert entries[2] == {"no": 4, "title": "药物制剂的稳定性", "page": 76}
    assert entries[3] == {"no": 5, "title": "制剂车间设计概述", "page": 101}


def test_extract_toc_entries_no_anchor():
    """无目录锚点 → 空列表（不误伤正文）。"""
    text = "# 第一章 绪论\n正文\n# 第二章 制药\n正文\n"
    batches = [{"idx": 1, "page_start": 1, "page_end": 99, "text": text, "content_list": None}]
    assert structure.extract_toc_entries(batches) == []


def test_extract_toc_entries_stops_at_hashed_chapter():
    """目录区域在第一个带 # 的章标题处结束（正文开始）。"""
    text = (
        "## 目录\n"
        "第一章 绪论  \n"
        "第二章 制药  \n"
        "# 第一章 绪论\n"      # 正文首个带 # 章 → 目录结束
        "正文\n"
        "# 第三章 制剂\n"
        "正文\n"
    )
    batches = [{"idx": 1, "page_start": 1, "page_end": 99, "text": text, "content_list": None}]
    entries = structure.extract_toc_entries(batches)
    assert len(entries) == 2, "目录提取应在正文首章前停止，不能把正文章收进目录"


# ── 目录驱动重建集成 ─────────────────────────────────


def test_toc_region_lines_not_chapters():
    """目录区域的目录行不成为章节（真实 bug：b8_工业药剂学前 9 个假章节）。"""
    text = (
        "封面\n"
        "## 目录\n"
        "第一章 绪论  \n"
        "第二章 药物制剂的设计与质量控制  \n"
        "第三章 药用辅料与应用  \n"
        "# 第一章 绪论\n正文内容…\n"
        "# 第二章 药物制剂的设计与质量控制\n正文内容…\n"
        "# 第三章 药用辅料与应用\n正文内容…\n"
    )
    result = _rebuild(text)
    titles = _titles(result)
    assert len(titles) == 3, f"应只有 3 个真章（目录行已跳过），实际 {titles}"
    assert titles[0] == "第一章 绪论"
    assert result["chapters"][0]["char_count"] > len("第一章 绪论"), "真章应包含正文"


def test_body_citation_not_chapter():
    """正文引用的法规条文（第一章 总则 等，不在目录白名单）不切章。

    真实场景：GSP/《药品管理法》条文被正文引用时带「第x章」，但这些章节
    不在教材目录中 → 目录驱动强制过滤。
    """
    text = (
        "## 目录\n"
        "第一章 药事法概述\n"
        "第二章 药品监督管理体制\n"
        "第三章 药品注册法律制度\n"
        "# 第一章 药事法概述\n正文…\n"
        "# 第一章 “总则”：共 4 条。\n附录条文…\n"          # 伪章，不在目录
        "# 第二章 “药品批发的质量管理”\n附录条文…\n"       # 伪章
        "# 第二章 药品监督管理体制\n正文…\n"
        "# 第三章 药品注册法律制度\n正文…\n"
    )
    result = _rebuild(text)
    titles = _titles(result)
    assert len(titles) == 3, f"伪章应被过滤，实际 {titles}"
    assert titles == ["第一章 药事法概述", "第二章 药品监督管理体制", "第三章 药品注册法律制度"]


def test_toc_order_advances_allows_skip():
    """目录顺序推进：正文按目录顺序识别，允许跳号（某章被 OCR 漏掉）。"""
    text = (
        "## 目录\n"
        "第一章 绪论\n"
        "第三章 药用辅料\n"
        "第五章 制剂车间\n"
        "# 第一章 绪论\n正文\n"
        "# 第三章 药用辅料\n正文\n"
        "# 第五章 制剂车间\n正文\n"
    )
    result = _rebuild(text)
    titles = _titles(result)
    assert titles == ["第一章 绪论", "第三章 药用辅料", "第五章 制剂车间"]


def test_no_toc_fallback_unchanged():
    """无目录（提取为空）→ 回退原逻辑：正文所有 第x章 都成立。"""
    text = "# 第一章 绪论\n正文\n# 第二章 制药\n正文\n"
    result = _rebuild(text)
    assert _titles(result) == ["第一章 绪论", "第二章 制药"]