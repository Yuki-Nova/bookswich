"""结构重建缺陷回归（2026-09-02，服务器故障排查报告 4.1/4.2 对应修复）。

缺陷 A（b16 药物分析化学，1~15 章被吞）：
  hash 风格统一过滤把「kind=ar 阿拉伯数字章」标题与去编号的目录白名单
  直接比对，带编号必失败 → 章标题被降级为正文 → 全书进 pre_matter 被丢。

缺陷 B（b17 民法学，第二章/第六章被吞）：
  目录 OCR 把「第二章 人格权法」识别成「第二节 人格权法」→ 目录条目缺章 →
  toc 白名单漏录 → 真章被当伪章降级。

修复要点（structure.py rebuild_v2）：
- hash 统一过滤豁免 kind="ar"（classify_heading 已要求行首带 #）
- _toc_match 失败时正文补锚：行首带 # + 标题长度 2~30 + 章号序进
  + 非「条文引用」形态（不带引号、非「共 N 条」）→ 补锚入库并记 warning
"""
from app.services import structure


def _rebuild(text: str) -> dict:
    batches = [{"idx": 1, "page_start": 1, "page_end": 99, "text": text, "content_list": None}]
    return structure.rebuild_v2(batches)


def _titles(result: dict) -> list[str]:
    return [ch["title"] for ch in result["chapters"]]


# ── 缺陷 A：hash 风格 + 阿拉伯数字章（b16 场景）────────────

def test_hash_style_arabic_chapter_survives():
    """hash 风格教材的「# N 标题」阿拉伯数字章不被目录白名单误杀。"""
    text = "\n".join([
        "1 概论 …… (1)",
        "2 药物的纯度检查和鉴别方法 …… (10)",
        "3 药物分析方法的设计和验证 …… (20)",
        "# 3 药物分析方法的设计和验证",
        "正文内容第一段…",
        "# 4 滴定分析法概论",
        "正文内容第二段…",
        "# 5 酸碱滴定法",
        "正文内容第三段…",
    ])
    result = _rebuild(text)
    assert _titles(result) == [
        "3 药物分析方法的设计和验证",
        "4 滴定分析法概论",
        "5 酸碱滴定法",
    ]
    # 修复前 1~3 章被降级后 all 进 pre_matter（384KB 正文被丢）；修复后不丢
    assert result["pre_matter_chars"] == 0


def test_hash_style_arabic_requires_hash_mark():
    """ar 章识别必须行首带 #（MinerU 标记过）：无 # 的数字开头正文行不切章。"""
    text = "\n".join([
        "1 概论 …… (1)",
        "3 药物分析方法的设计和验证 …… (20)",
        "# 概论",
        "正文…",
        "# 学习目标",
        "目标内容…",
        "# 知识要点",
        "要点内容…",
        "3 药物分析方法的设计和验证",
        "更多正文…",
    ])
    result = _rebuild(text)
    assert _titles(result) == ["概论"]
    ch = result["chapters"][0]
    assert any("药物分析方法的设计和验证" in l for l in ch["lines"]), "无 # 的数字行应作为内容"


# ── 缺陷 B：目录 OCR 漏录 → 正文补锚（b17 场景）────────────

def test_toc_ocr_gap_chapters_anchored():
    """目录把「第二章 人格权法」识别成「第二节」→ 白名单缺章 → 正文真章补锚。"""
    text = "\n".join([
        "## 目录",
        "第一章 民法的基本原则",
        "第二节 人格权法 …… 109",
        "第一节 人格权概述 …… 109",
        "第三章 物权",
        "第四章 合同",
        "第五章 侵权责任",
        "第六节 继承法 …… 210",
        "第七章 诉讼时效",
        "# 第一章 民法的基本原则",
        "正文一…",
        "# 第二章 人格权法",
        "正文二…",
        "# 第三章 物权",
        "正文三…",
        "# 第四章 合同",
        "正文四…",
        "# 第五章 侵权责任",
        "正文五…",
        "# 第六章 继承法",
        "正文六…",
        "# 第七章 诉讼时效",
        "正文七…",
    ])
    result = _rebuild(text)
    assert _titles(result) == [
        "第一章 民法的基本原则",
        "第二章 人格权法",
        "第三章 物权",
        "第四章 合同",
        "第五章 侵权责任",
        "第六章 继承法",
        "第七章 诉讼时效",
    ]
    anchored = [w for w in result["warnings"] if "目录漏录，正文补锚" in w]
    assert len(anchored) == 2, f"应为 2 条补锚 warning，实际 {result['warnings']}"
    # 补锚章应带正文（不是空壳）
    ch2 = result["chapters"][1]
    assert any("正文二" in l for l in ch2["lines"])


def test_toc_gap_pseudo_statute_not_anchored():
    """正文引用的法规条文（带引号/共 N 条、章号不序进）不能借补锚复活。"""
    text = "\n".join([
        "## 目录",
        "第一章 药事法概述",
        "第二章 药品监督管理体制",
        "第三章 药品注册法律制度",
        "# 第一章 药事法概述",
        "正文…",
        "# 第一章 “总则”：共 4 条。",
        "附录条文…",
        "# 第二章 “药品批发的质量管理”",
        "附录条文…",
        "# 第二章 药品监督管理体制",
        "正文…",
        "# 第三章 药品注册法律制度",
        "正文…",
    ])
    result = _rebuild(text)
    assert _titles(result) == [
        "第一章 药事法概述",
        "第二章 药品监督管理体制",
        "第三章 药品注册法律制度",
    ]
    assert not any("目录漏录，正文补锚" in w for w in result["warnings"])


def test_toc_anchor_requires_sequential_no():
    """补锚要求章号序进：重复该章号（总则条文跟在第一章真章后）不补锚。"""
    text = "\n".join([
        "## 目录",
        "第一章 概述",
        "第二章 历史",
        "第三章 附录",
        "# 第一章 概述",
        "正文…",
        "# 第一章 总则：共 12 条。",
        "条文…",
        "# 第二章 历史",
        "正文…",
        "# 第三章 附录",
        "正文…",
    ])
    result = _rebuild(text)
    assert _titles(result) == ["第一章 概述", "第二章 历史", "第三章 附录"]
    assert not any("目录漏录，正文补锚" in w for w in result["warnings"])
    ch1 = result["chapters"][0]
    assert any("总则" in l for l in ch1["lines"]), "条文标题应降级为第一章内容"


# ── 缺陷 A2：书末习题解答区重复 ar 章标题（b16 batch_18）────

def test_board_exercise_answers_dup_arabic_chapters_absorbed():
    """习题解答区按章分组的重复 ar 标题不产生伪章；首次 ar 真章照常成立。

    b16 真实形态：batch_01「内容提要」board 后紧跟「# 1 概论」真章（必须退出
    board）；batch_18「## 习题解答」board 内「## 2 药物的纯度检查和鉴别方法」
    等答案分组标题（已在真章入库过）必须降级；OCR 变体「紫外一可见」vs
    入库「紫外—可见」按宽松归一化匹配。
    """
    text = "\n".join([
        "1 概论 …… (1)",
        "2 药物的纯度检查和鉴别方法 …… (10)",
        "11 紫外—可见分光光度法 …… (110)",
        "## 内容提要",
        "这是一本关于药物分析的书…",
        "# 1 概论",
        "第一章正文…",
        "# 2 药物的纯度检查和鉴别方法",
        "第二章正文…",
        "# 11 紫外—可见分光光度法",
        "第十一章正文…",
        "## 习题解答",
        "## 2 药物的纯度检查和鉴别方法",
        "1. 解: 因标准 NaCl 溶液…",
        "## 11 紫外一可见分光光度法",
        "2. 解: 标准曲线…",
    ])
    result = _rebuild(text)
    assert _titles(result) == [
        "1 概论",
        "2 药物的纯度检查和鉴别方法",
        "11 紫外—可见分光光度法",
    ], f"重复 ar 标题应降级，实际 {_titles(result)}"
    # 习题解答区域节点存在，且答案内容未被拆成伪章
    all_lines = []
    for ch in result["chapters"]:
        for b in ch.get("children", []):
            if b.get("board"):
                all_lines.extend(b.get("lines", []))
    assert any("1. 解:" in l for l in all_lines), "习题解答内容应保留在 board 节点内"
    assert any("2. 解:" in l for l in all_lines), "变体分组标题的答案内容也应保留"