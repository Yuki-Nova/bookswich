# CLAUDE.md — bookswich 项目上下文

本文件是 Claude Code 的项目上下文，启动时自动加载。开发前先读本文，保持与既有架构和决策一致。

## 项目是什么

教材 PDF → 结构化 Markdown 的工具。上传 PDF 教材 → MinerU 云 API 分批解析成 Markdown → 规则法结构重建（修正标题层级）→ 网页下载整本/单章/原始版 Markdown，供 Obsidian / Typora 使用。

> ⚠ **2026-08-06 去 RAG 化（用户决策）**：原 RAG 知识库问答功能（检索/向量/DeepSeek/评测）已全部移除，知识库路线改为 **Hermes + Obsidian**（Obsidian 双向链接建库，Hermes 的 obsidian skill 负责笔记操作）。本项目**不再做任何 RAG/问答**，只保留「解析 + 格式修正 + 下载」。

> 📐 **2026-08-10 表格智能转换（门禁制）（2026-08-18 U 阶段已退役为可选）**：`exporter.py` 的 `_table_quality_gates`（6 道门禁：
> 闭合配对 / 无 colspan·rowspan / 无游离文本 / 行列规整 / 2~8 列 / 2~20 行 / 单格 ≤300 字符）通过 → `format_table_md`
> 转 Markdown 表格（`<eq>`→`$` 含实体解码、公式内 `|`→`\vert`、公式外 `|`→`\|`、表格前后空行分隔）；
> 未通过 → 保留 MinerU HTML 原样。**禁止为公式渲染牺牲表格格式**——历史教训：HTML→MD 全量转换导致
> 数据列表/合并单元格/多分布并表列错乱（2026-08-09 用户暴怒回退）。
>
> 🎯 **2026-08-18 表格大一统（U 阶段，用户拍板：全 HTML）**：`_node_to_md`/`export_rebuilt`/`export_obsidian_zip`
> 加 `tables="html"|"md"` 参数，**默认 `tables="html"`**——所有表格保留原生 HTML（结构 100% 保真含合并单元格/宽表），
> 表内公式以 `$..$` 定界符输出，由 Obsidian 社区插件 **html-table-math**（MIT，装在用户 vault，不在仓库）渲染；
> 门禁转换降级为可选 `tables="md"`。历史教训依旧：**即使 tables="md"，也绝不牺牲表格格式换公式渲染**（合并表始终保留 HTML）。
> 运行时依赖：Obsidian 侧需装 html-table-math 插件才有 HTML 表内公式渲染。详见 docs/TECH.md §1.9。
> **2026-08-17 单元格净化链**：`format_table_md` 单元格处理 = 实体解码 → 公式间双空格压平（`$A$  $B$`→`$A$ $B$`）
> → `normalize_math` 定界符净化 → 竖线转义；`normalize_math` 内置相邻公式压平（`(?<!\$)\$\s{2,}\$(?!\$)`，
> 排除 `$$` 块级），MD 转换与 HTML 保留两条路径统一受益。

## 技术栈

| 环节 | 选型 |
|------|------|
| 后端 | Python FastAPI（uvicorn，127.0.0.1:8000；生产 8001 + nginx 反代） |
| 前端 | Vue 3 + Vite（127.0.0.1:5173）+ KaTeX；登录页 + 上传/进度/下载/对比 |
| 解析 | MinerU 云 API（分批 25 页，落盘缓存 + 图片落盘，配额双维度记账） |
| 存储 | SQLite（data/kb.db，books 表；WAL + busy_timeout 30s） |
| 访问控制 | `auth.py`：`api_token`（程序）+ `web_password`（浏览器会话 token，B5） |

## 三段流水线

```
PDF → [MinerU 分批解析] → [结构重建(规则法修正格式)] → [导出 Markdown 下载]
```

- **MinerU 只负责内容忠实转换，结构（标题层级）绝不信任 MinerU 推断**——扫描书标题严重错乱（章被压成 `##`、练习题被标成 `#`）
- 每段独立可跑、可单测

## 目录结构

```
bookswich/
├── backend/
│   ├── app/
│   │   ├── main.py              # 入口：CORS + lifespan(init_db)
│   │   ├── config.py            # pydantic-settings，.env 配置；空值回退默认
│   │   ├── db.py                # SQLite books 表 + 轻量列迁移
│   │   ├── api/routes.py        # REST 接口：books/upload/parse/chapters/export/quota
│   │   └── services/
│   │       ├── mineru_client.py # 分批解析 + 落盘缓存 + 配额记账(quota.json)
│   │       ├── structure.py     # 规则法+目录驱动结构重建（核心模块）
│   │       ├── exporter.py      # 导出 rebuilt/raw/按章 + 表格大一统(默认全 HTML)
│   │       ├── verify_export.py # 导出物静态回归扫描 8 规则（A4）
│   │       ├── audit_orphans.py # DB vs 磁盘孤儿产物只读审计（B3）
│   │       ├── compare.py       # 质检报告 + 按章 raw/rebuilt diff
│   │       ├── oss_images.py    # OSS 图片上传（幂等 + 部分失败降级 B4）
│   │       └── auth.py          # api_token 程序通道 + web_password 会话通道（B5）
│   ├── scripts/                 # 运维 CLI（只读优先，删改默认 dry-run）
│   │   ├── ops.py               # rebuild/export/import 子命令
│   │   ├── vault_health.py      # vault 体检
│   │   ├── server_health.py     # --check 健康检查 / --cleanup 备份清理
│   │   ├── audit_orphans.py     # 孤儿产物审计（默认 dry-run）
│   │   ├── audit_tables.py      # 真实教材表格公式分布只读审计
│   │   ├── golden_samples.py    # 黄金样本基线采集/校验
│   │   ├── smoke_playwright.py  # 生产冒烟（console/5xx 收集）
│   │   └── verify_export.py     # 导出物扫描 CLI
│   ├── tests/                   # pytest（182 用例）
│   │   ├── conftest.py          # 共享 fixture（rebuilt_full 全书导出）
│   │   ├── test_exporter.py     # 导出/公式规范化/OSS 外链
│   │   ├── test_structure_arabic.py  # 阿拉伯数字章/节标题识别
│   │   ├── test_table_md.py     # 表格门禁 + HTML→Markdown 转换（md 模式）
│   │   ├── test_toc_driven.py   # P0-5 目录驱动
│   │   ├── test_html_boundary.py# HTML 表格与标题边界（A1）
│   │   ├── test_clean_export.py / test_verify_export.py / test_compare.py
│   │   ├── test_api_regression.py / test_auth.py / test_quota.py
│   │   ├── test_parse_failure.py / test_oss_failure.py / test_db_concurrency.py
│   │   └── test_golden_samples.py / test_audit_orphans.py / test_logging.py
│   ├── pyproject.toml           # [tool.pytest.ini_options] testpaths=["tests"]
│   ├── requirements.txt
│   └── .env                     # MINERU_API_KEY + web_password + OSS_*（不入库）
├── frontend/
│   └── src/
│       ├── App.vue              # 单页：登录 + 上传/进度/下载/对比
│       ├── auth.js              # authFetch（统一带 X-Auth-Token）+ authedUrl
│       ├── components/          # UploadPanel/BookDetail/ComparePanel/ChapterDiff/
│       │                        # SideBySideView/PdfViewer/SidebarPanel/LoginPanel
│       ├── composables/useParseTask.js
│       ├── __tests__/auth.test.js        # vitest
│       └── style.css            # 纸墨朱砂红设计令牌
├── data/
│   ├── raw/        原始 PDF
│   ├── md/<book>/  分批解析 Markdown（batch_XX_pN-M.md，文件名即页区间元数据）
│   │               + content_list JSON + images/（图片文件，md 里相对路径引用）
│   ├── build/<book>/  structure.json + outline.md + page_index.json（结构重建产物）
│   ├── kb.db        SQLite（books 教材元数据，WAL 模式 + busy_timeout 30s）
│   └── quota.json   每日配额记账
├── export/         已导出 Markdown（只放产物，调试脚本放 backend/scripts/）
└── docs/           TODO.md（方案里程碑）+ TECH.md（技术文档）+ PRODUCTION.md（生产变更）
```

> `data/` 与 `export/` 是运行时产物，已被 `.gitignore` 忽略；`data/kb.db.bak-<日期>` 为清理前人工备份。

## API 一览（prefix /api）

- `GET /health` — 健康检查
- `POST /books` / `GET /books` / `GET /books/{id}` — 教材 CRUD
- `POST /books/upload` — multipart 上传 PDF，PyMuPDF 自动检测页数
- `POST /books/{id}/parse` — 后台线程分批解析（进度轮询 GET /books/{id}）
- `GET /api/books/{id}/chapters` — 章节列表
- `GET /api/books/{id}/export?format=rebuilt|raw|obsidian&chapter=N&images=local|oss` — 导出 **ZIP**
  （默认 local：书名.md + images/ 子目录，解压即 Obsidian/Typora 可读；`images=oss`：图片上传
  OSS `OSS_BUCKET` 桶，md 引用改公网 URL，zip 只含文本）
- `POST /api/auth/login` — 用 `web_password` 换会话 token（B5 访问控制）
- `GET /quota` — MinerU 配额状态（页数 + 文件数双维度）
- `GET /books/{id}/compare` + `GET /books/{id}/compare/chapter/{n}?as=diff|markdown` — 质检报告 / 按章 diff
- `GET /books/{id}/media/{file_path:path}` — 取教材图片等静态资源（需鉴权，前端用 `authedUrl`）
- `GET /settings` — 前端运行时配置
- `POST /books/{id}/import-obsidian` — 按章导入 vault（幂等，强制 OSS 外链）
- `DELETE /books/{id}` — 删除教材（解析中拒绝）

> 除 `/health` 与首页静态资源外，`/api` 需鉴权：浏览器带 `X-Auth-Token`，程序用 `api_token`。

## 关键约定（用户明确决策，不可违背）

1. **MinerU 解析后的表格不做任何内容判断与转换**：HTML `<table>` 原样保留（内容/属性/结构零改动）。唯一允许的加工是纯排版换行 `table_html.replace("><", ">\n<")`——HTML 解析忽略换行，但消灭超长单行（CodeMirror 超长行是 Typora 6GB 内存的元凶）。
2. **公式定界符规范化**（Typora 不识别带空格的 `$ $`）：行内 `$ P(X=k) $` → `$P(X=k)$`（去内侧首尾空格）；块级 `$$...$$` 保持 `$$\n内容\n$$` 独占行。交替正则单次替换：`re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$", re.S)`——先 $$ 后 $，分两次 sub 会让行内规则二次配对块级公式的 `$`。`\(` / `\)` 混入时转普通括号。
   **2026-08-17 相邻公式压平**：`normalize_math` 开头先 `re.sub(r"(?<!\$)\$\s{2,}\$(?!\$)", "$ $", text)`
   ——MinerU 用 `$  $`（结束$+双空格+开始$）连接相邻行内公式，Typora 对第二个公式的前导空格定界符
   识别不稳；`(?<!\$)(?!\$)` 排除 `$$` 块级（防空块级公式被压坏）。
3. **结构重建是规则法 + 目录驱动**：清除所有 `#` 标记，按教材编号体系正则重新打标（第x章→第x节/x.y→一、→（一）），目录行过滤（`第x章 ……… 数字`），特殊板块区域化（思考与练习/习题/内容提要等 board 标题开启区域，区域内标题行降级为内容）。
   **P0-5 目录驱动（2026-08-16）**：numbered 风格教材从「## 目录」锚点提取目录条目
   `extract_toc_entries`（页码 OCR 丢失容忍），目录区域整段跳过 + 正文「第x章」必须命中
   目录白名单并按目录顺序推进（伪章——正文引用条文/目录残渣——标题行降级为内容），
   目录有页码时 page_range 用真实页码（p121）；hash 风格/目录提取失败完全回退旧逻辑。
4. **导出 markdown 服务于 Obsidian/Typora**：CommonMark + `$...$` 公式；不做 RAG 相关的分块/检索设计。
5. **图片必须随解析落盘并打包导出**：MinerU markdown 图片是相对路径 `![](images/xxx.jpg)`，
   `ExtractResult.images` 里的字节必须落盘 `data/md/<book>/images/`（2.7 节链路）。
   导出用 `export_zip` 打包 `书名.md` + 引用的 images/ → 浏览器下载 zip。用户把解压后的
   整个文件夹（md + images/ 同目录）放进 Obsidian vault 即显示图片。
6. **图片转 OSS 外链（2026-08-07，vault 纯文本化的默认交付形态）**：`images=oss` 时 `oss_images.OssImageUploader`
   把图片传 `OSS_BUCKET` 桶（杭州 public-read，key=`<书名>/images/<hash>.jpg`，hash 恒定幂等，
   head 命中跳过），md 引用替换为 quote 编码的 OSS URL。`.env` 需配
   `OSS_ACCESS_KEY_ID/OSS_ACCESS_KEY_SECRET/OSS_BUCKET/OSS_REGION`。
   `import-obsidian` 强制走 oss 模式，vault 只落文本（11.5MB→2.7MB），多端同步更轻。
7. **解析缓存完整性**：`_batch_complete` 逐批核对 content_list 的 img_path 文件是否齐全，
   缺图批次自动重跑补图。⚠ 不能只看 images/ 目录非空（批次共享目录，会误判跳过）。
8. **导出深度清洗（2026-08-16，借鉴 mineru-tianshu）**：`exporter.clean_markdown` 对正文
   做双层 HTML 反转义（`&amp;gt;`→`>`）+ 删 `<del>` 幻觉标签 + 空行折叠（节点级 join 后折叠，
   逐行无跨行上下文）；MinerU 的 HTML 表格行**绝不参与清洗**（约定 #1）；`normalize_html_images`
   把 `<img src="images/x">` 归一化为 `![](images/x)`，`IMG_RE` 兼容两种写法（打包/统计链路
   经 `_img_rel(m)` 取路径）；`format_table_md` 单元格同样做实体解码。刻意不做 Tianshu 的
   整段重复去重与 `~`/`\mathrm` 处理——数学教材公式风险大于收益。

## 常用命令

```powershell
# 后端启动（backend/ 目录）
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 测试（backend/ 目录）
$env:PYTHONIOENCODING='utf-8'      # Windows 控制台跑 pytest 必设，否则中文输出 UnicodeDecodeError
.venv\Scripts\python.exe -m pytest  # 182 用例

# 前端（frontend/ 目录）
npm install --registry=https://registry.npmmirror.com   # 国内源
npm run dev        # http://localhost:5173
npm run test           # vitest 18 用例
npm run verify:build   # 前端门禁（vite build + verify_build 产物检查），改动后必须跑

# 运维 CLI（backend/ 目录，.venv 内；删改类默认 dry-run）
.venv\Scripts\python.exe scripts\ops.py rebuild --id 1 --title "医药应用概率统计" --dry-run
.venv\Scripts\python.exe scripts\vault_health.py --json
.venv\Scripts\python.exe scripts\server_health.py --check
.venv\Scripts\python.exe scripts\audit_orphans.py --dry-run
.venv\Scripts\python.exe scripts\verify_export.py <export.md>

# 手动跑结构重建（backend/ 目录，.venv 内）
.venv\Scripts\python.exe -c "from app.services import structure; print(structure.run(1, '医药应用概率统计'))"
```

## 数据现状（2026-10-05 实测）

**DB（`data/kb.db`，books 表）3 本**：

| id | 书名 | 页数 | 状态 | 进度 | 配额页 |
|---|---|---|---|---|---|
| 1 | 医药应用概率统计 | 369 | parsed | 15/15 | 325 |
| 6 | 研究生入学考试分析化学学习指导与试题精解 | 316 | parsed | 13/13 | 266 |
| 8 | 工业药剂学（吴正红 周建平） | 830 | structure_ok | 34/34 | 105 |

**磁盘产物（`data/md`、`data/build`）4 个目录**——比 DB 多一个
`b8_基础医学概论 …`：该目录有 `page_index.json`（1.6MB，2026-09-14）但**无 structure.json/outline.md**，
且 DB 无对应记录（已删教材或历史残留）。

- 孤儿图片：**工业药剂学 267 个、8.3MB**（MinerU 重跑 hash 变化残留，见踩坑速查）
- `data/raw` 4 个 PDF：3 个 81MB 测试书（同名重复上传）+ 分析化学 10.9MB + 工业药剂学 81.5MB
- 清理前数据库备份：`data/kb.db.bak-20261005`（5.3MB）

### 两处已知产物管理问题（2026-10-05 发现，未修）

1. **`tests/test_parse_failure.py` 会污染真实 `data/md/`**：`api_env` 用 `monkeypatch` 把
   `settings.data_dir` 指向 tmp_path，但 `POST /books/1/parse` 启动的**后台线程**在 monkeypatch
   撤销后才执行，此时 `settings.md_dir` 已恢复为真实值 → 每次跑全量 pytest 都会在
   `data/md/` 下生成空的 `b1_测试书/`。（已定位：单跑该文件即复现）
2. **`audit_orphans` 按 `b<id>` 前缀比对**：同 id 不同书名（如 `b8_工业药剂学` 与
   `b8_基础医学概论`）前缀相同 → 无 DB 记录的基础医学概论被判定为「非孤儿」，审计漏报。

## 待办路线（docs/TODO.md 完整版）

- **去 RAG 化重构**（2026-08-06）：已完成——RAG 代码/数据/接口全部移除，只留解析+导出+下载
- 待办：Obsidian 布置（用户自行进行，Hermes 用 obsidian skill 配合）；P2 保留：章节知识点大纲、公式/表格专项（历史 RAG 目标已废弃，仅保留非 RAG 项）

## 踩坑速查（完整记录见 docs/TECH.md）

- uvicorn 不热加载 .env：改 key 必须重启进程
- **图片丢失教训（2026-08-06）**：MinerU 的 images 在 `ExtractResult.images` 不在 markdown
  里，只存 markdown 全书无图；修复后旧批次靠 `_batch_complete` 自动重跑补图
- **MinerU 重跑图片 hash 会变**：同一页重跑生成新 hash → images/ 残留旧图；导出只打包
  引用图片，清理残留用「未被任何 md 引用即删」
- **目录行页码带括号**（`…… (1)`）：`RE_TOC_LINE` 要支持 `（\d+）|\(\d+\)` 结尾
- **章标题带 `·` 前缀**（`# · 第四章`）：`RE_CH_LEVEL1` 容忍 `[·•]?`，标题 `lstrip("·•")`
- 端口占用：8000 被旧进程占用时 uvicorn 启动报 [Errno 10048]，先 `Get-NetTCPConnection -LocalPort 8000` 查占用并杀旧进程（实测踩过：旧代码进程导致 RAG 接口"复活"的假象）
- `python-multipart` 缺失 → `Form data requires "python-multipart"`
- pydantic-settings 空字符串 env 覆盖默认值：config.py 用 `field_validator(mode="before")` 空值回退
- sqlite3 不显式 commit：裸脚本 INSERT 后要显式 commit
- 导出的中文文件名用 `filename*=UTF-8''{quote(name)}`；`Cache-Control: no-store` 防浏览器缓存旧版导出
- PowerShell 内联 python 多行脚本用 here-string：`@'...'@ | python -`

## 开发流程

- 功能开发先出详细计划（写入 docs/TODO.md，含 P0~P2 优先级、里程碑、风险），用户批准后再动手
- 新工具/爬虫类项目倾向在项目根目录另建独立文件夹
- 改动后端后跑 pytest；改动前端后跑 `npm run verify:build`（vite build + 构建产物门禁）
- 验证用真实数据（如《医药应用概率统计》解析/导出），不能只查服务状态
