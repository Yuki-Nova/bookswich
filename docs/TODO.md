# bookswich — 教材 PDF → 结构化 Markdown（项目状态与待办）

> 历史完整记录见 `docs/TODO.md.bak-20260817`（900+ 行 RAG 时代至今的逐批记录）。
> 本文档为精简版：当前状态 + 关键决策 + 待办。

## 项目定位（2026-08-06 去 RAG 化后）

教材 PDF（含纯扫描版）→ MinerU 云解析 → **规则法+目录驱动结构重建** → 导出 Markdown
（整本/单章/原始/Obsidian 版），供 Obsidian/Typora 使用。**不做 RAG/问答**（知识库 = Obsidian + Hermes）。

## 核心链路（全部完成并验证）

```
PDF → [MinerU 分批解析 25页/批 + 缓存 + 配额] → [结构重建 规则法+目录驱动] → [导出 表格门禁+净化链+深度清洗]
```

### 解析（mineru_client.py）
- [x] 分批解析落盘 `data/md/<book>/batch_XX_pN-M.md` + content_list JSON + images/（图片字节落盘）
- [x] 缓存完整性 `_batch_complete`：逐批核对 img_path 文件（不能只看共享 images/ 目录非空）
- [x] 配额双维度：优先页数（1000/日，超了进普通队列）+ 文件数（5000/日硬上限，原子占位）

### 结构重建（structure.py，核心）
- [x] 规则打标：清除 MinerU `#`，按编号体系重打（第x章→第x节/x.y→一、→（一）），特殊板块区域化
- [x] **P0-5 目录驱动（2026-08-16）**：`extract_toc_entries` 从「## 目录」锚点提取条目（页码 OCR 丢失容忍）；
      目录区域整段跳过 + 正文「第x章」白名单强制 + 目录顺序锚定 + 页码锚定（p121）；
      hash 风格/无目录完全回退旧逻辑
- [x] 阿拉伯数字章/节标题、`·` 前缀、目录行括号页码等 OCR 变体支持
- [x] 真树化重建（嵌套 children + 层级跳变警告 + 目录页整页降权）

### 导出（exporter.py）
- [x] 表格 6 道门禁（2026-08-10 用户拍板：能转的必是规整表格）→ `format_table_md` 转 MD；未过保留 HTML
- [x] **单元格净化链（2026-08-17）**：实体解码 → 公式间双空格压平 → 定界符净化 → 竖线转义；
      `normalize_math` 内置相邻公式压平（`(?<!\$)\$\s{2,}\$(?!\$)` 排除块级）
- [x] 深度清洗（2026-08-16 借鉴 mineru-tianshu）：双层反转义 / `<del>` / 空行折叠 / `<img>` 归一化
- [x] 图片：zip 只打包引用图；`images=oss` 上传 OSS（hash 幂等）vault 纯文本化
- [x] Obsidian 版：按章拆分 + 00_总览 MOC + 无章节「全文」兜底 + **导入幂等**（解压前清旧目录，2026-08-17）

### 质检与运维
- [x] compare 质检报告（表格门禁原因分布/图片缺失/节编号连续性）+ 按章 raw vs rebuilt diff（v2 缓存）
- [x] 生产部署：阿里云 ECS（systemd + nginx + WebDAV vault），部署流程沉淀在 skill `bookswich-deploy`
- [x] webdav 403 修复（2026-08-17）：nginx `limit_except` 补 GET/HEAD（Obsidian 下载文件用 GET）；
      宝塔 reload 必须 `nginx -s reload`

## 关键用户决策（不可违背）

1. MinerU 表格内容零改动（仅排版换行）；门禁转换是唯一例外（转 MD 表格）
2. 公式定界符规范化（Typora 不识别带空格的 `$ $`）；导出服务于 Obsidian/Typora
3. 结构重建不信任 MinerU 标题推断；P0-5 起目录驱动（numbered 教材）
4. 导出 markdown 不做 RAG 分块设计
5. 图片随解析落盘并打包；OSS 外链为 vault 纯文本化默认交付形态
6. `import-obsidian` 强制 oss 模式；导入幂等（清理旧目录）
7. 禁止为公式渲染牺牲表格格式（2026-08-09 全量转换翻车教训）

## 测试状态

- [x] pytest **97 用例全绿**（结构/表格门禁/导出/清洗/目录驱动/配额/compare）
- [x] 真实数据验证：b1 概率统计（11 章/349 表）、b6/b8/b9/b11（20 章/10 章等）重跑无退化
- [x] vault 全量体检（2026-08-17）：6 本教材 `VAULT_ALL_CLEAN`（章节一致/表格正常/公式内侧空格 0/双空格 0）

## 数据现状（服务器，2026-08-17）

- 教材 6 本已导入 vault（教材/ + 扩展教材/）：概率统计、西方经济学、管理学、基础医学概论、工业药剂学、药事法
- 旧版遗留已清理：分析化学试题精解、药物分析化学（全 HTML 表格旧产物，已从 vault 删除）

## 待办

### P2 远期
- [ ] Obsidian 教材导入插件（OBP-1~6）：Obsidian 内直接「导入 PDF → 解析 → 生成 vault 笔记」
- [ ] 章节知识点大纲生成（非 RAG）
- [ ] 公式/表格专项质检增强

### 运维备忘
- [ ] 服务器旧 `app.bak-*` / `dist.bak-*` 定期清理（保留最新 2~3 份）
- [ ] vault 教材定期重导（结构逻辑更新后 `structure.run` + import-obsidian，均幂等）

## 风险与对策

| 风险 | 对策 |
|------|------|
| OCR 目录页码丢失 → 目录驱动失效 | extract_toc_entries 页码容忍（None 回退批区间） |
| 表格门禁误判（该转的没转） | 门禁保守（宁保留 HTML 不转错）；质检报告统计原因分布 |
| MinerU 输出脏数据（实体/重复行/幻觉标签） | 导出深度清洗（表格行除外） |
| 结构逻辑更新后线上教材旧产物 | 重跑 `structure.run` + 重导（幂等） |
