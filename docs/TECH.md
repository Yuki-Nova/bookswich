# bookswich 技术文档

> 教材 PDF → MinerU 解析 → 结构重建（修正格式）→ Markdown 导出/下载 → Obsidian vault → llm-wiki 记忆层
> 测试样本：《医药应用概率统计》第 3 版（369 页，纯扫描版）
> 更新日期：2026-08-07
>
> ⚠ **2026-08-06 去 RAG 化**：按用户决策，知识库路线改为 Hermes + Obsidian（双链建库），
> 本项目的 RAG 功能（分块/检索/问答）全部移除。本文 2.3~2.5 节仅作历史记录保留。
>
> 🧠 **2026-08-06 llm-wiki 记忆层上线**：Obsidian 之上新增 Hermes 专用记忆层（见 1.2 节）。
>
> 🖥️ **2026-08-07 前端重设计**：Vercel 设计语言（sticky 导航 + 拖拽上传 + 教材卡片 + 状态徽标）。
>
> 🔄 **2026-08-07 Obsidian 同步升级为 WebDAV**：vault 走 wsgidav + Nginx 反代（如 `https://webdav.example.com/`），
> Obsidian Remotely Save 多端自动同步；bookswich 服务器端导入直接写 WebDAV 同步目录（详见 1.2 节）。
>
> 📐 **2026-08-10 表格智能转换（门禁制）**：6 道质量门禁通过 → HTML 表格转 Markdown（表格内公式可渲染）；
> 未通过 → 保留 HTML 原样。详见 1.3 节。

---

## 1. 架构总览

```
┌─────────────┐   ┌──────────────┐   ┌─────────────┐
│  前端 Vue3  │──▶│  FastAPI     │──▶│ MinerU 云API│
│ 上传/解析   │   │  /api/*      │   │ 分批解析     │
│ 进度/下载   │◀──│              │◀──│              │
└─────────────┘   └──────┬───────┘   └─────────────┘
                         │
                    SQLite kb.db
                    (books 教材元数据)
```

- **后端**：FastAPI（`backend/app/`），Python 3.10+，uvicorn 单进程
- **前端**：Vue 3 + Vite（`frontend/`），`/api` 代理到 `127.0.0.1:8000`
- **数据**：SQLite 单文件 `data/kb.db`（零部署，备份即拷文件）
- **核心链路**：上传 PDF → MinerU 分批解析（落盘缓存）→ 规则法结构重建 → 导出 Markdown（整本/单章/原始）→ 网页下载，供 Obsidian 等工具使用 → **llm-wiki 记忆层（Hermes 专用）**

## 1.2 知识库下游：Obsidian vault + llm-wiki 记忆层（2026-08-06 建，2026-08-07 同步方案升级）

教材导出后的知识库是**两层结构**：

```
┌─────────────────────────────────────────────────────────┐
│ Obsidian vault（教材原文，唯一事实源，只读）               │
│ 服务器: /srv/obsidian-vault/obsidian  (WebDAV 同步目录)   │
│ 本地:   /path/to/local/vault                            │
│ 教材/<书名>/  按章拆分 + 00_总览 MOC（图片 OSS 外链，vault 纯文本） │
│ 同步: WebDAV https://webdav.example.com/                │
│       (Nginx 反代 127.0.0.1:8081 wsgidav，provider 根=/srv/obsidian-vault) │
│       Obsidian Remotely Save 自动建 obsidian/ 子目录同步  │
└──────────────────────────┬──────────────────────────────┘
                           │ 调取（[[obsidian:教材/<书名>/<章节>|显示名]]）
┌──────────────────────────▼──────────────────────────────┐
│ llm-wiki 记忆层（Hermes 专用，vault 之外）                │
│ /path/to/llm-wiki  (WIKI_PATH)                          │
│ SCHEMA.md / index.md / log.md                           │
│ raw/（原始资料，只读引用）  entities/ concepts/           │
│ comparisons/ queries/  _archive/                        │
│ 作用：Hermes 复习时快速调取教材知识点的索引/记忆层         │
└─────────────────────────────────────────────────────────┘
```

**同步链路（2026-08-07 实测确认）**：
- 服务器：wsgidav（`/etc/wsgidav.yaml`，provider_mapping `/` → `/srv/obsidian-vault`，systemd `wsgidav.service`）
  经 Nginx 反代到 WebDAV 域名（宝塔面板"反向代理"功能配置，允许 WebDAV 方法）
- 客户端：Obsidian Remotely Save 填 WebDAV URL + 账号密码；
  插件自动在远程根下建 `obsidian/` 子目录存放同步内容 → **实际同步目录 = `<vault>/obsidian/`**
- bookswich 服务器端 `OBSIDIAN_VAULT_DIR=<vault>/obsidian`——导入直接写该目录，
  Obsidian 多端自动增量拉取，**无需下载**（导入 → 同步全程服务器完成）
- ⚠ **路径陷阱（2026-08-07 踩坑）**：WebDAV 域名若同时挂静态站，静态网站根 ≠ wsgidav 同步目录；
  `OBSIDIAN_VAULT_DIR` 必须指向 Obsidian 实际同步的目录（vault 根下嵌套的 obsidian/ 子目录）
- ⚠ **改 .env 必须重启**：生产 bookswich 后端跑 8001 端口（8000 是 herbtool），由 systemd `bookswich.service`
  管理；宝塔面板"重启网站"只重启 Nginx ≠ 重启后端，改 `.env` 后必须 `systemctl restart bookswich` 才生效
- ⚠ **Remotely Save 默认双向同步会污染服务器**：平板端旧 vault 若含 images/ 会覆盖干净版本；
  修复：服务器清空重建 → 平板删旧 vault → 首次同步选"Download remote to local"单向拉取 →
  设置里加忽略规则 `*/images/**`

**关键约束（用户明确要求）**：
- 教材原文**保持原样**，wiki 只做知识点提炼/索引，不复制教材全文
- wiki 目录**绝不建进 vault**（vault 走 WebDAV 多端同步，加目录会污染同步）
- 记忆层**只有 Hermes 用**，整理粒度以复习调取效率为准
- 引用教材格式：`[[obsidian:教材/<书名>/<章节>|显示名]]`；wiki 页面用 frontmatter + wikilink + 受控标签（SCHEMA taxonomy）

**配置**：`WIKI_PATH=/path/to/llm-wiki`（写入 Hermes 配置，修改后下个会话生效）

**维护流程**：每次操作先 orient（读 SCHEMA + index + 最近 log）→ 提炼教材知识点建 concept/entity 页 → 交叉链接 → 登记 index.md + log.md。底层模式见 bundled `llm-wiki` skill，本机落地约束见 `llm-wiki-obsidian-memory` skill。

## 1.3 表格智能转换：门禁制（2026-08-10）

**问题**：MinerU 表格内公式用 `<eq>LaTeX</eq>` 标签（非 `$...$`），HTML `<table>` 内的定界符不被
Typora/Obsidian 渲染；而 HTML→Markdown 全量转换在真实教材中导致列错乱（数据列表、合并单元格、
多分布并表）。2026-08-09 曾多次尝试后用户拍板回退。

**方案（用户拍板：能转的必是规整表格）**：
```
<table> 块 → _table_quality_gates（6 道门禁）
   全过 → format_table_md → Markdown 表格（公式可渲染）
   任一不过 → 保留 MinerU HTML 原样（格式永远正确）
```

**6 道门禁**（`exporter.py` 常量可调）：
| 门禁 | 检查 | 防什么 |
|------|------|--------|
| G1 闭合配对 | `<table` 数 == `</table>` 数 | 未闭合表格吞后续内容 |
| G2 无合并 | 无 colspan/rowspan | Markdown 无合并单元格语义 |
| G3 无游离文本 | 挖掉 td 后无残留文本 | 正文长字符串混入表格 |
| G4 行列规整 | 每行 td 数一致 | 参差表格列错乱 |
| G5 尺寸 | 2~8 列、2~20 行 | 数据列表/超宽表 |
| G6 单格长度 | 单格 ≤300 字符 | 单格长文本爆炸 |

**转换函数 `format_table_md`**：
- `<eq>...</eq>` → `$...$`（先 `html.unescape` 解码 `&lt;`/`&gt;`，否则 LaTeX misplace &）
- 竖线转义：公式内 `|` → `\vert `（数学模式语义正确），公式外 `|` → `\|`（Markdown 转义）
- 表格前后空行分隔（防相邻表格被渲染器合并）

**实测（《医药应用概率统计》349 个表格）**：176 转 Markdown（列零错乱）+ 173 保留
（138 合并单元格 + 33 超宽 + 2 超长）。转换的 176 个自动校验列一致性 0 错乱。

**测试**：`tests/test_table_md.py`（15 用例：门禁 8 + 转换 5 + 集成 2）+ `conftest.py` 共享 fixture。

**铁律**：禁止为公式渲染牺牲表格格式——门禁不通过的表格宁可 HTML 原样，不强行转换。

## 2. 核心流程

### 2.1 解析（MinerU 分批）

- 完整模式 `extract_batch`，**25 页/批**
- **配额规则（2026-08-07 实测修正）**：免费额度不是「1000 页/天」——**优先 2 解析页数每日 1000 页**（高优先级解析模式按页计），
  解析**总限制每日 5000 份文件**（一份 PDF 无论多少页均按 1 算）；落盘缓存 + 幂等重跑不重复计费
- 每批 Markdown 落盘 `data/md/<book>/batch_XX_pN-M.md` + 同名 `.json`（content_list）
- content_list 元素含 `{type, text, page_idx, text_level, bbox}`：
  - 标题特征：`type=="text"` 且 `text_level in (1,2)`（**注意：目录页标题也会被标记，精确页码因此被污染，P0 用批区间页码**）
  - 噪音类型：`header` / `page_number` / `footer`
- **图片落盘（2026-08-06 修复）**：markdown 里图片引用是相对路径 `![](images/xxx.jpg)`，
  图片字节在 `ExtractResult.images`（list[Image]，name+data）——**必须随批次落盘到
  `data/md/<book>/images/`**（旧版只存 markdown 丢了图片，导致解析结果无图，见 2.7）
- **缓存完整性检查 `_batch_complete`**：md 存在 + 该批次 content_list 引用的每个
  img_path 文件都已存在才算缓存完整；缺图批次自动重跑补图（重跑会重新计配额）
  ⚠ **坑**：images/ 目录是所有批次共享的，检查不能只看目录非空（第一批重跑后
  后续批次会误判完整而跳过）——必须逐批核对 img_path 文件
- 配额记账 `data/quota.json`；重跑走缓存不重复消耗

### 2.2 结构重建（`services/structure.py`）

**核心决策：不信任 MinerU 的 `#` 标题层级**，全部清除后按教材编号体系规则重打标：

| 规则 | 匹配 | 级别 |
|------|------|------|
| 章 | `^第[一二三…]章` | level 1 |
| 节 | `^第x节` / `^x.y` | level 2 |
| 小节 | `^一、`（节内降级为 level 3，cn_sub） | level 3 |
| 次小节 | `^（一）`（cn_sub 内升为 level 4） | level 4 |
| 板块 | 思考与练习/习题/上机训练题/内容提要/参考答案/知识链接/附录 等 | board |

关键机制：
- `sec_kind` 状态机："第x节"后"一、"降级为 cn_sub，且**连续"二、""三、"保持降级**（首次修复的 bug）
- `last_sub_node` 正文归属：正文行归入最近子标题节点
- `RE_TOC_LINE` 丢弃目录页行（"第x章 标题……页码"）
- 前置过滤：封面/简介/CIP/前言
- 节编号连续性质检（OCR 漏标题时报警）
- 产物：`data/build/<book>/structure.json` + `outline.md`（大纲报告，人工抽查用）

### 2.3 分块（`services/chunker.py`）⚠ 已废弃（去 RAG 化，历史记录）

- 按权威标题树递归切块，每块 ≤800 字，重叠 10%
- 全书 1414 块 / 92.3 万字 / 平均 653 字 / 无超长块
- 写库前自动注册占位教材记录

### 2.4 检索（`services/retriever.py`）⚠ 已废弃（2026-08-06 删除，历史记录）

**FTS5 + jieba 预分词**（关键坑）：
- FTS5 `unicode61` tokenizer 把连续中文当整体 token（"贝叶斯"匹配不到"贝叶斯公式"）
- 解法：入库/查询统一用 **jieba `cut_for_search`** 空格分词——整词+子词都进索引（"假设检验"→"假设 检验 假设检验"），任何分词方式都能命中
- **分词一致性是必修课**：曾经索引用 `cut` 而查询整词短语匹配 0 命中 → 问答报"未检索到相关内容"
- FTS 插入必须显式 `commit`（`with get_conn()` 只回滚不自动提交）
- FTS 表结构变更需先 `DROP TABLE IF EXISTS chunks_fts` 再建

**混合检索 RRF**：
- `keyword_search`（BM25）+ `vector_search`（余弦，`data/vectors/book_N.npy` + `_ids.json`）
- RRF 融合（k=60），向量缺失时自动降级 FTS-only（`vector_status="skipped"`）

### 2.5 问答（DeepSeek）⚠ 已废弃（2026-08-06 删除，历史记录）

- prompt：仅基于教材片段回答 + 末尾列出引用出处；片段标注 `<书名> <章节路径>（页码区间）`
- 模型 `deepseek-chat`（服务端解析为 deepseek-v4-flash，别名兼容）
- 实测样本：样本方差公式、泊松分布 E(X)=λ/D(X)=λ、中心极限定理、假设检验步骤

### 2.6 导出（`services/exporter.py`）

**v4 策略（用户决策）**：
- **MinerU 表格原样保留**——不做"内容行 vs 表格行"判断（项目无法可靠判断，判断即错乱）；
  仅做**排版换行**（标签间插 `\n`，HTML 语义零改动）避免 CodeMirror 超长单行（20KB→最长 1KB）
- **公式定界符规范化**：
  - 行内 `$ ... $` 去内空格（Typora 不识别 `$` 后空格的定界符）
  - 块级 `$$...$$` 保持 $$ 独占行多行格式
  - `\(` / `\)` 混入公式 → 转普通括号（MinerU 偶发混用 LaTeX 定界符）
- 按章导出：`export?chapter=N` + `/api/books/{id}/chapters`
- **zip 打包（2026-08-06）**：导出接口返回 `zip`（`书名.md` + `images/` 子目录，仅打包
  md 实际引用的图片）——markdown 图片引用是相对路径 `images/xxx.jpg`，单文件 md 在
  导出目录会失效，必须 md 与 images/ 同级打包；解压后 Obsidian/Typora 直接可读
- **Obsidian 版导出 `format=obsidian`（2026-08-06）**：按章拆分（性能：整本 871KB/4 万行
  在 Obsidian 会卡，每章 30~370KB 秒开）+ `00_总览.md` MOC（各章 `[[链接]]`，无 .md 后缀）
  + 各章独立 `images/`（图片按章分摊，只打包本章引用）
- **一键导入 `POST /api/books/{id}/import-obsidian`**：需 .env 配置 `OBSIDIAN_VAULT_DIR`，
  直接解压写入 `<vault>/<obsidian_sub_dir>/<书名>/`（默认 sub_dir=教材，路径穿越防护）；
  **服务器部署下 OBSIDIAN_VAULT_DIR 指向 WebDAV 同步目录（/srv/obsidian-vault/obsidian），导入即多端同步**
  ⚠ 已知限制：导入依赖 `data/build/<book>/structure.json`（结构重建产物），缺失会报
  「结构重建产物缺失」；无章节结构的文件（论文/单篇）暂不支持导入（2026-08-07 记录，待修）
- 中文文件名：`Content-Disposition` RFC 5987 `filename*=UTF-8''`（zip 后缀）
- 防缓存头：`Cache-Control: no-store`
- **OSS 外链模式（2026-08-07）**：`export?images=oss` / `import-obsidian` 默认走外链——图片上传
  `OSS_BUCKET` 桶（需 public-read），md 里 `![](images/xxx.jpg)` 替换为
  `https://<OSS_BUCKET>.<OSS_REGION>.aliyuncs.com/<书名>/images/<hash>.jpg`
  （quote 编码），zip/vault 只含文本。幂等：图片名是 MinerU hash，key 恒定，
  head_object 命中即跳过，重复导出不重复上传。vault 纯文本化（11.5MB → 2.7MB）。
  .env 新增：`OSS_ACCESS_KEY_ID/OSS_ACCESS_KEY_SECRET/OSS_BUCKET/OSS_REGION`
  （用户自有 OSS 账号；服务器同地域部署时可设
  `OSS_INTERNAL=true` 走内网 endpoint 免公网流量费；配 CDN 后改 `OSS_IMAGE_BASE_URL`）。
  已知限制：MinerU 偶发缺图（b6 有 1 张 290751…jpg 源数据无字节且 git 历史也没有），
  该引用保留相对路径会裂图，重跑 hash 会变也无法对回——记录备查。
- KaTeX 全书扫描：6603 公式，失败 3 个（OCR 截断残缺公式，无法可靠自动修复）

### 2.7 图片处理（2026-08-06 修复，重要）

**问题**：MinerU 云 API 的 markdown 里图片是相对路径引用 `![](images/xxx.jpg)`，图片字节在
`ExtractResult.images` 字段里。旧版 mineru_client 只落盘 markdown/content_list，**丢掉
images → 解析结果全书无图**（实测 b1 111 张、b6 455 张引用全部无文件）。

**修复链路**：
1. 解析层：`_extract` 透传 `result.images` → 落盘时写入 `data/md/<book>/images/<name>`
2. 缓存完整性：`_batch_complete` 逐批核对 content_list 的 img_path 文件是否齐全，
   缺则重跑补图（旧库自动补，无需手工清理）
3. 导出层：`export_zip` 打包 `书名.md` + 引用的 `images/` → 浏览器下载 zip，
   解压后相对路径引用直接可用（Obsidian/Typora 原生支持）

**验证（2026-08-06 实测）**：b6 分析化学 455 张引用全部落盘（MinerU 偶发缺 1 张，
zip 优雅跳过）；导出 zip 5.6MB（md 706KB + 453 图）解压结构正确。

**坑**：
- MinerU 重跑同一页图片 hash 可能变化 → images/ 残留旧图，导出只打包引用的不打包残留；
  如需清理：删除未被任何 md 引用的文件
- 目录行页码带括号（`…… (1)`）的教材（如分析化学），`RE_TOC_LINE` 必须支持
  `（\d+）|\(\d+\)` 结尾，否则目录行被误认成章
- MinerU 偶发 `# · 第四章`（章标题带 `·` 前缀），`RE_CH_LEVEL1` 需容忍 `[·•]?` 前缀，
  标题文本用 `lstrip("·•")` 清理

## 3. 前端要点

- **2026-08-07 重设计（Vercel 设计语言）**：`style.css` 全量 token 化（白底/近黑文字 #171717/链接蓝 #0072f5、
  shadow-as-border、卡片内层 #fafafa 微光、圆角 8px/6px、权重 400/500/600）；`App.vue` sticky 导航 +
  状态 pill 徽标（配额/Obsidian 连接/API Key）；`UploadPanel.vue` 拖拽上传区 + 教材卡片列表（替代硬表格）+
  解析进度条 + 移动端适配（≤640px）；字体 Geist（Google Fonts CDN + system-ui 回退，国内失败不影响）
- 上传页：进度轮询（`parse_progress`）、配额显示
- 下载：教材列表点下载（整本/原始/Obsidian 版/章节下拉）

## 4. API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/quota` | MinerU 配额 |
| GET | `/api/books` | 教材列表 |
| POST | `/api/books/upload` | 上传 PDF（multipart，PyMuPDF 检测页数） |
| POST | `/api/books/{id}/parse` | 后台线程分批解析 |
| GET | `/api/books/{id}` | 教材详情 |
| GET | `/api/books/{id}/chapters` | 章节列表 |
| GET | `/api/books/{id}/export?format=rebuilt\|raw\|obsidian&chapter=N&images=local\|oss` | 下载 ZIP（rebuilt/raw 整本含图；obsidian 按章拆分+MOC；images=oss 图片转 OSS 外链，zip 只含文本） |
| POST | `/api/books/{id}/import-obsidian` | 一键导入 vault（需配置 OBSIDIAN_VAULT_DIR + OSS，图片转 OSS 外链） |
| GET | `/api/settings` | 前端配置状态（vault 是否已连接） |

## 5. 运行方式

```powershell
# 后端（backend/ 下）
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端（frontend/ 下）
npm run dev    # http://localhost:5173，/api 代理到 8000

# 测试
cd backend; .venv\Scripts\python.exe -m pytest   # 10 用例
```

## 6. 数据落盘结构

```
data/
├── raw/          # 原始 PDF（上传）
├── md/<book>/    # 分批解析 Markdown + content_list JSON + images/（图片文件）
├── build/<book>/ # structure.json + outline.md（大纲报告）
├── kb.db         # SQLite：books 教材元数据
└── quota.json    # MinerU 每日配额记账
```

## 7. 踩坑记录（血泪）

1. **rollup win32-x64-msvc native 损坏**：npmmirror 镜像下载的 `.node` 文件损坏（1.4MB），强制重装恢复（2.6MB）
2. **uvicorn 不热载**：改 `.env`/服务代码需重启进程；生产 bookswich 后端是 systemd `bookswich.service`（8001 端口，8000 是 herbtool），宝塔"重启网站"≠重启后端，必须 `systemctl restart bookswich`
3. **FTS 中文分词**：unicode61 整串 token + 索引/查询分词上下文不一致 → 双坑，统一 `cut_for_search` 解决
4. **FTS 事务**：`with get_conn()` 不自动提交，插入必须显式 `conn.commit()`
5. **结构重建状态机**：cn_sub 降级后必须保持（"一、"后的"二、"仍降级）
6. **目录页污染**：content_list 的 text_level 标题在目录页也被标记 → 精确页码锚定不可靠，用批区间页码
7. **表格判断陷阱**：MinerU 版面分析把"表格+周围文字"识别成一个大 `<table>`（rowspan 跨行塞文字/公式）——任何内容判断都会误伤，最终决策：**原样保留**
8. **Typora 大文件**：CodeMirror 对超长单行 O(n²)，HTML 表格必须排版换行；公式定界符内空格 Typora 不认
9. **embedding 模型下载**：hf-mirror 大文件限速断连（95MB ONNX），fastembed 期望文件名 `model_optimized.onnx`；网络就绪后 `scripts/download_model.py`（断点续传）补下
10. **jieba 缓存**：首次加载 0.3s+ 正常；`jieba.cache` 在 `%TEMP%`
11. **WebDAV 同步路径陷阱（2026-08-07）**：Obsidian Remotely Save 填根 URL 会自动建 `obsidian/` 子目录同步，
    实际同步目录 = `<vault>/obsidian/`；`OBSIDIAN_VAULT_DIR` 必须指向它（不是 vault 根本身，
    也不是 WebDAV 域名挂的静态网站根）；改 .env 后重启 systemd 服务
12. **MinerU 配额（2026-08-07 实测）**：不是"1000 页/天"；优先 2 解析页数 1000 页/天 + 总限制 5000 份文件/天（PDF 无论页数按 1 计）

## 8. 已知限制 / 待办

- 3 个 OCR 截断残缺公式无法自动修复（导出时 KaTeX 失败，Typora 显示原文）
- OCR 会把中文句子误包进 `$...$`（KaTeX warn 可渲染；Typora MathJax 显示可能异常）
- 精确页码被目录页污染（P2：需修 content_list 页码锚定）
- RAG 功能已于 2026-08-06 移除（去 RAG 化，知识库走 Obsidian）；踩坑 3/4/9/10 为历史记录
