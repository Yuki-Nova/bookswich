# bookswich — 教材解析·知识库·RAG 问答系统

## 项目概述

教材 PDF → MinerU 解析成 Markdown → 结构重建 → 分块向量化 → 知识库 → 混合检索 + DeepSeek 问答。
**原则：教材不进 LLM 上下文，知识库只存结构化文本块 + 向量索引，提问时只检索 Top-K 相关块。**

## 测试样本

《医药应用概率统计》第 3 版（科学出版社 2018，高祖新/韩可勤/言方荣 主编），369 页。
**纯扫描版（读秀/超星）**：无文本层、无 PDF 书签、无印刷目录页。文件名误写为"医药信息检索.pdf"。

## 侦察结论（已实测，2026-08-05）

1. 纯扫描版，PyMuPDF 提取不到任何文本，`get_toc()` 返回 0，前 70 页未见目录页
2. MinerU 云 API 输出**不带页码**（纯 markdown 流）→ 页码靠分批解析获得
3. MinerU 标题层级**严重错乱**：章标题「第二章 随机事件和概率」= `##` 与节同级；「上机训练题」= `#` 高于章；封面书名 = `#`
4. OCR 文本质量高：公式转 LaTeX、表格转 HTML 结构完整
5. 图片：封面 2 页装饰图可丢弃；正文内容图（SPSS 截图等）保留引用
6. 结构重建策略：**不信任 MinerU 的 `#` 推断，全部清除后按教材编号体系规则重新打标**

## 技术选型

| 环节 | 选型 | 说明 |
|------|------|------|
| 后端 | FastAPI | 异步，流式输出 |
| 前端 | Vue 3 + Vite + Element Plus | 上传页 + 问答页 |
| 解析 | MinerU 云 API | 分批 20~30 页/批，落盘缓存 |
| 向量化 | bge-m3（sentence-transformers 本地） | 中文教材，免费离线 |
| 向量库 | sqlite-vec 或 ChromaDB | 文件型，零部署 |
| 关键词检索 | SQLite FTS5（BM25） | 混合检索 |
| LLM | DeepSeek API | 流式回答 |

## 里程碑

### P0 — 最小闭环（当前，按顺序执行）

- [x] **P0-1 项目骨架**：backend(FastAPI) + frontend(Vue3) 可运行空壳
- [x] **P0-2 解析服务**：MinerU 分批解析封装 + Markdown 落盘缓存 + 配额记账
- [x] **P0-3 结构重建管线**：规则打标 + 前置过滤 + 装饰图过滤 + 大纲报告
- [x] **P0-4 分块器**：按权威标题切块 + 质检
- [x] **P0-5 检索问答**：FTS5+jieba 实测命中准确；DeepSeek 问答实测通过；
      向量检索降级 P1（embedding 模型下载受阻：hf-mirror 大文件限速、HF 官方超时、modelscope 无 ONNX 版）
- [x] **P0-6 端到端验证**：全书 369 页解析入库（15 批，配额 369/1000）+ 6 个问题问答验证全部正确（含公式 LaTeX、章节引用）

### P1 — 体验完善

- [x] **后端上传接口**：multipart 上传 + PyMuPDF 自动检测页数（实测 369 页正确）
- [x] **Vue 上传页**：文件上传、教材列表、解析进度轮询、配额显示
- [x] **Vue 问答页**：教材范围切换、markdown 渲染（marked）、引用出处展示
- [x] **多教材管理**：books 表多记录、问答按教材隔离
- [x] ~~**向量检索补回**~~（2026-08-06 去 RAG 化已废弃：检索层/embedding 代码已删）
- [x] **公式渲染（KaTeX）**：markdown-it + markdown-it-texmath 解析阶段渲染 + auto-render 兜底 HTML 表格内公式（验证 PASS）
- [x] **Markdown 下载**：exporter 服务（rebuilt 结构重建版 / raw 原始合并版），API 下载 + 前端教材列表下载按钮（中文文件名 RFC5987 编码，实测 200）
- [x] **公式渲染修复**：行内公式空格规范化 + `\(...\)` 定界符修复（KaTeX 全书扫描失败 10→3，剩余为 OCR 截断残缺公式）；Typora 实测通过
- [x] **表格内容行判定 v2**：结构特征判据（单填充单元格 + 行位置 + $$）替代纯长度启发式——"其中…性质："短行、SPSS 跨列表头区分正确
- [x] **正式测试套件**：backend/tests/test_exporter.py（pytest，8 用例全绿），`cd backend && .venv\Scripts\python -m pytest tests/ -q`
- [x] **Typora 大文件优化 B2**：按章导出（chapters 接口 + export?chapter=N，单章 ~114KB）+ 前端章节下拉
- [x] **问答"未检索到相关内容"修复**：FTS 分词一致性——索引与查询统一 jieba `cut_for_search`（整词+子词都进索引，如"假设检验"→"假设 检验 假设检验"），修复长文本分词上下文导致短语匹配 0 命中；重建 FTS 后 5 词命中 + 端到端问答 3/3
- [x] **导出策略 v4（用户决策）**：MinerU 表格**原样保留不做内容判断**（仅排版换行防超长行）；公式定界符规范化（行内去内空格 + 块级多行 + `\(...\)` 转普通括号，KaTeX 扫描失败 10→3，余为 OCR 截断）
- [x] **Typora 大文件优化 B1**：HTML 表格→标准 Markdown 表格（已被 v4 表格保留策略取代，记录备查）
- [x] ~~问答页流式输出（SSE）~~（2026-08-06 去 RAG 化已废弃：ChatPanel 问答页已删）

### Agentic RAG（P1，2026-08-06 新增，用户指定下一步优先）

> ⚠ **2026-08-06 用户决策：放弃机械 RAG 路线，知识库转 Obsidian 管理。本章节仅作历史记录，不继续执行。**

### 重构：去 RAG 化 · 转 Obsidian 交付（2026-08-06，用户决策，当前任务）

**目标**：bookswich 简化为「教材 PDF → MinerU 解析修正 → 网页下载 Obsidian 笔记」工具，砍掉全部 RAG 知识库问答。

**保留**
- [x] 上传 PDF + PyMuPDF 页数检测
- [x] MinerU 分批解析（配额记账、落盘缓存）
- [x] 结构重建（规则法修正格式）
- [x] Markdown 导出（rebuilt/raw/按章）
- [x] 网页下载（教材列表 + 下载按钮 + 章节下拉）

**砍掉（RAG 相关）**
- [x] RAG-1 检索层：`services/retriever.py`（FTS5+jieba+向量+RRF）→ 删除
- [x] RAG-2 agent 层：`services/rag_agent.py`（路由/改写/大纲/CRAG/trace）→ 删除
- [x] RAG-3 API：`/chat`、`/books/{id}/build` → 从 routes.py 删除（实测 404）
- [x] RAG-4 前端：`ChatPanel.vue`、问答 tab → 删除（App.vue 改单页）
- [x] RAG-5 评测：`backend/eval/`（golden_set、脚本、报告）→ 删除
- [x] RAG-6 数据：清空 chunks 表、删 chunks_fts / qa_logs 表、删 `data/vectors/`、删冗余 `backend/kb.db`
- [x] RAG-7 依赖：移除 fastembed（requirements.txt 已清，代码零引用）
- [x] RAG-8 配置：`.env` 移除 DEEPSEEK_API_KEY（MINERU_API_KEY 保留），config.py DeepSeek 字段删除

**Obsidian 适配（新增）**
- [x] OB-0 用户决策：Obsidian 布置由用户自行进行（Hermes + Obsidian 方案，obsidian skill 操作笔记），本项目仅交付标准 Markdown
- [x] **OB-2 兼容性验证**：`$` 公式 Typora/Obsidian 渲染 OK；HTML 表格内 `<eq>` 公式两处均不渲染
      → 促成 2026-08-10 表格门禁转换（见文末小节）

**文档同步**
- [x] DOC-1 requirements.txt / README.md / CLAUDE.md / docs/TODO.md / docs/TECH.md 更新为去 RAG 化状态

**验证（2026-08-06 实测）**
- [x] pytest（test_exporter 保留）全绿（10 用例）
- [x] 前端 `npm run build` 通过
- [x] 端到端：启动后端 → books 列表 ✓ → chapters ✓ → export rebuilt 871KB ✓ → /api/chat 404 ✓ → /api/books/1/build 404 ✓（注意：需先杀 8000 旧进程）

### 图片链路修复（2026-08-06 完成，用户反馈"解析结果没有图片"）

- [x] **IMG-1 诊断**：MinerU markdown 图片是相对路径 `![](images/xxx.jpg)`，字节在 `ExtractResult.images`——旧版只存 markdown 丢了图片（b1 111 张 / b6 455 张引用全无文件）
- [x] **IMG-2 解析层修复**：`_extract` 透传 images → 落盘 `data/md/<book>/images/`
- [x] **IMG-3 缓存完整性**：`_batch_complete` 逐批核对 img_path 文件（⚠ 不能只看共享 images/ 目录非空，首次实现导致只补了前几批——第二次修复逐批核对）
- [x] **IMG-4 导出 zip**：`export_zip` 打包 `书名.md` + 引用的 images/（缺失图优雅跳过）；API 返回 zip；前端按钮改「下载 ZIP」
- [x] **IMG-5 结构规则加固**：目录行括号页码（`…… (1)`）+ 章标题 `·` 前缀 → 分析化学 18 章完整重建
- [x] **IMG-6 验证**：b6 455 引用全落盘（MinerU 偶发缺 1），zip 5.6MB 解压结构正确；b1 补图后台进行中
- [x] **IMG-7 b1 补图收尾**：15/15 完成，111 引用全落盘 0 缺失，清理 1422 个残留旧图；导出 zip 3.4MB 含 110 图（封面装饰图被结构重建过滤，符合预期）

### Obsidian 集成（2026-08-06 完成，vault=本地 Obsidian 教材目录）

- [x] **OB-1 按章拆分导出**：`format=obsidian` zip——`<书名>/00_总览.md`（MOC [[链接]]，无 .md 后缀）+ `NN_<章名>/<章名>.md + images/`（每章只带本章图）
- [x] **OB-2 一键导入**：`POST /api/books/{id}/import-obsidian` → `<vault>/教材/<书名>/`（OBSIDIAN_VAULT_DIR 配置于 .env，路径穿越防护）
- [x] **OB-3 前端**：「🗂 Obsidian 版」下载链接 + 「📓 导入 Obsidian」按钮（vault 未配置不显示）+ 头部 vault 连接状态徽标
- [x] **OB-4 性能验证**：整本 871KB/4 万行 → 每章最大 370KB（第十一章，表格多）其余 ≤150KB，Obsidian 秒开；图片按章分摊
- [x] **OB-5 实测导入**：b1（11 章/110 图）、b6（18 章/453 图）已写入 vault，MOC 链接规范可用

### 图片转 OSS 外链（2026-08-07 完成，vault 纯文本化为多端同步铺路）

- [x] **OSS-1 配置**：backend/.env 新增 OSS_ACCESS_KEY_ID/SECRET（用户自有 OSS 账号
      已实测 PUT/HEAD/DELETE 全通）/OSS_BUCKET=<用户桶>/OSS_REGION=<地域>；
      config.py 新增 oss_configured/oss_endpoint/oss_image_base（可切内网/CDN）
- [x] **OSS-2 上传器**：services/oss_images.py — OssImageUploader 幂等上传（head 命中跳过），
      key 规则 `<书名>/images/<hash>.jpg`，URL quote 编码
- [x] **OSS-3 导出外链**：export_obsidian_zip / export_zip 加 image_mode=local|oss（默认 local 兼容），
      oss 模式 md 引用改 URL、zip 只含文本（b1 3.4MB→320KB）；routes 加 images 参数 + import-obsidian 默认 oss
- [x] **OSS-4 测试**：test_exporter 新增 4 用例（URL 改写/无 images/非法参数/未配置报错）全绿 14/14
- [x] **OSS-5 端到端**：真实导出 b1（110 图上传 16.6s，幂等重导 7.6s 内容一致）、b6（453 图 52.7s）；
      抽查 OSS URL 全部 200；vault 重导两本书后 11.5MB→2.72MB，无 images/ 残留，脏文件 .jpg.md 清除
- [x] **OSS-6 前端**：下载/导入按钮统一 images=oss，文案标注「图转 OSS」；npm run build 通过
- [ ] **OSS-7 已知限制**：b6 第五章 1 张图（290751…jpg）MinerU 缺字节，源数据与 git 历史均无，
      该引用保留相对路径（裂图），重跑 hash 会变无法对回——记录备查，可接受（0.2%）

### 网页端删除教材 + 无编号教材结构重建兜底（2026-08-08 已执行）

- [x] **DEL-1 删除教材**：`DELETE /api/books/{id}`（删 raw PDF + data/md/ + data/build/ + db 记录；
      解析中 409、幂等 404、raw 仅限 data/raw/ 内防穿越）
- [x] **DEL-2 前端**：教材卡片「🗑 删除」按钮（confirm 确认）
- [x] **FALLBACK-1 无编号兜底**：structure.py 对无编号教材（正文标题无「第x章」）用 MinerU # 标题 +
      目录页清单过滤重建；标题归一化匹配（公式/全角破折号）
- [x] **FALLBACK-2 验证**：b3《西方经济学（宏观部分）》重建 11 章全识别、内容覆盖 97%
      （即生产问题 1 的修复，见下）；pytest 14/14；前端 build 通过
- **git**: 7f2c65e

### P2 — 进阶（原 RAG 相关条目废弃，保留表格/大纲等非 RAG 项）

- [ ] 章节知识点大纲自动生成（配合复习流程）
- [ ] 按检索块出练习题
- [ ] 公式/表格检索专项优化
- [ ] 本地 MinerU 部署（拿 page_idx 精确页码）

### Obsidian 教材导入插件（P2 远期，2026-08-06 规划，待开发）

在 Obsidian 内直接完成「导入 PDF 教材 → 解析 → 生成 vault 笔记」，不再需要打开网页。

**架构决策**：解析引擎留在 bookswich 后端（MinerU 是 Python，插件是 TS 无法内嵌），
插件通过 HTTP 调 bookswich API（上传/解析/导入已具备），只做 Obsidian 端 UI 与进度展示。

- [ ] **OBP-1 插件骨架**：manifest.json + main.ts + esbuild 构建（Obsidian 社区插件标准结构，本地安装/BRAT）
- [ ] **OBP-2 后端适配**：确认 CORS 允许 Obsidian（file:// 或本机）、必要时加简单鉴权 token（MinerU key 不暴露给插件）
- [ ] **OBP-3 命令与 UI**：命令面板「导入教材 PDF」+ 文件选择模态框 + 解析进度条（轮询 /api/books/{id}）
- [ ] **OBP-4 导入流程**：调 upload → parse（后台）→ 轮询完成 → 调 import-obsidian（或插件直接复制文件到 vault）→ 提示打开 00_总览.md
- [ ] **OBP-5 体验**：多教材列表、重复导入检测、失败重试（复用缓存续跑）
- [ ] **OBP-6 测试发布**：本地 vault 实测导入流程 + 构建发布包

**风险与对策**：

| 风险 | 对策 |
|------|------|
| Obsidian 插件 API 学习成本 | 从官方 sample plugin 起步，只做最小命令+模态框 |
| 后端未启动时插件不可用 | 插件检测后端 health，未启动提示先跑 start.ps1 |
| 鉴权缺失 | 本机使用可先用 localhost 绑定 + 可选 token 头 |
| 插件与 bookswich 版本耦合 | API 版本化字段预留（/api/v1 或兼容字段） |

**前置**：一键启动脚本（start.ps1/stop.ps1）已完成，插件可直接复用「后端必先启动」的前提。

## 风险与对策

| 风险 | 对策 |
|------|------|
| MinerU 标题错乱 | 结构重建规则法，不信任其推断，全部重打标 |
| 无目录无书签 | 规则识别教材编号体系（第x章/x.y/一、/（一）），大纲报告人工抽查 |
| 输出无页码 | 分批解析得页区间，引用给页范围 |
| 封面/装饰图噪音 | 前置部分过滤 + 版面特征过滤（位置/尺寸/图注） |
| 结构错误毒数据入库 | 质检关卡：大纲报告确认后才入库，异常章节标记待修 |
| 配额超限（优先 1000 页/日 + 文件 5000/日） | 双维度记账：优先不足排队不中断、文件数满额才中断 + 失败重试不重复计费 + Markdown 落盘缓存 |
| 标题规则误判 | 规则调整重跑（零 MinerU 成本），P1 可加 LLM 校正兜底 |

## 数据落盘结构（约定）

```
data/
├── raw/          原始 PDF
├── md/<book>/    分批解析的 Markdown（batch_01.md ...）
├── build/        重建后的结构化文本（章节 JSON）
├── kb.db         SQLite（books/chunks/qa_logs）
├── vectors/      向量库文件
└── quota.json    每日配额记账
```

## 生产问题记录（2026-08-07 用户反馈；问题 1/3 已解决，问题 2 待处理）

1. ~~**导入 Obsidian 报「结构重建产物缺失」**~~（**已解决 2026-08-08**）：b3《西方经济学（宏观部分 第7版）》
   是无编号教材走不了结构重建——7f2c65e 增加无编号兜底（MinerU # 标题 + 目录页清单过滤），
   b3 重建 11 章全识别、内容覆盖 97%
2. ~~**无章节文件不能导入**~~（**已解决 2026-08-11**）：某些文件（无章节结构）无法走 `import-obsidian`；
   `export_obsidian_zip` 增加无章节兜底——structure.json 缺失或 chapters 为空时整本合并为一个「全文」章节
   （正文=原始批次合并），本地/OSS 两种图模式均支持；顺带解决「缺 structure.json 导入报错」（见文末小节）
3. ~~**MinerU 配额规则修正**~~（**已解决 2026-08-10**）：实测免费额度不是「1000 页/天」——**优先 2 解析页数每日 1000 页**，
   解析**总限制每日 5000 份文件**（一份 PDF 无论多少页均按 1 算）。配额模型已按双维度改造（见文末小节），
   前端/文档文案已同步

---

## 开源化改造（2026-08-07 规划，待批准执行，先不改）

**目标**：把高度依赖本地 Obsidian / 个人 OSS / WebDAV 的工具，转为人人可用的开源项目。

**现状个人化依赖**（6 处）：

| 依赖 | 现状 | 开源障碍 |
|------|------|----------|
| MinerU API key | .env 配置，uvicorn 不热加载 | 每人需自己申请 key，无引导 |
| 阿里云 OSS | import-obsidian 强制 oss 模式，未配 OSS 直接 400 | 别人无阿里云账号无法导入 |
| Obsidian vault 路径 | OBSIDIAN_VAULT_DIR 服务器本地目录 | 别人可能不用 Obsidian 或只想下 zip |
| 配置形态 | 全靠 .env | 改配置需重启进程 |
| 部署形态 | start.ps1 本地双进程，无 Docker | clone 需装 Python+Node 两套环境 |
| 仓库 | 无 git，库内含测试 PDF/解析产物 | 无法分发与贡献 |

### P0 — 去个人化（别人能用）

- [ ] **OPEN-1 MinerU key 网页端填入**：存 data/mineru_key.json，优先于 .env，解析线程现读生效（保存即生效，免重启）；无 key 时前端引导申请
- [ ] **OPEN-2 OSS 降为可选增强**：未配 OSS 时图片走 local（zip 内 images/）；import-obsidian 同时支持带图目录版，不再强制 oss
- [ ] **OPEN-3 Obsidian 路径降为可选便利**：默认主路径 = 下载 Obsidian 版 zip 自行拖入 vault；import-obsidian 仅本机/自托管场景显示
- [ ] **OPEN-4 首次引导**：无 key 时前端显示申请链接 + 填框，替代干巴巴的「未配置」警告
- [x] **OPEN-5 清理库内个人数据**：根 .gitignore 已拦 data/、export/、*.pdf、docs/ui-*.png（2026-08-07 完成；
      data/ 整体忽略故无需 data/.gitignore，示例结构可后续补）
- [x] **OPEN-6 .env.example 全量注释化**（17 行全注释；parse_batch_size 等新字段可后续补）

### P0 — 开源要素

- [x] **OPEN-7 git init + LICENSE(MIT) + 初始提交**（2026-08-07 完成，已推送 github.com/Yuki-Nova/bookswich）
- [ ] **OPEN-8 Dockerfile + docker-compose**：后端 + 前端 build 产物 + data/ 数据卷，一条命令起
- [ ] **OPEN-9 单端口部署**：Vite build 产物由 FastAPI StaticFiles 托管，替代双进程双端口
- [ ] **OPEN-10 CI**：GitHub Actions 跑 pytest + 前端 build
- [ ] **OPEN-11 README 重写**：Docker 快速开始、截图、FAQ、MinerU key 申请引导

### P1 — 通用化（好用）

- [ ] **OPEN-12 存储抽象层**：图片/产物 provider 接口 —— local / 阿里云 OSS / S3 兼容 / WebDAV（覆盖用户个人栈的依赖，转成通用能力）
- [ ] **OPEN-13 鉴权（可选）**：自托管场景 Token 认证；本地默认无鉴权但文档写明风险
- [ ] **OPEN-14 i18n** 中英文界面（视目标受众再定）

### P2 — 生态

- [ ] **OPEN-15 Obsidian 导入插件**（复用 OBP-1~6 既有规划）
- [ ] **OPEN-16 GitHub Pages 文档站**

**待定决策**：
1. 定位：纯本地单机工具（推荐）vs 可服务器自托管（需鉴权）——建议两者兼容：默认本地跑，Docker 可选部署，鉴权做成可选
2. 存储抽象第一版范围：只做 local + S3 兼容（覆盖 OSS/各云），WebDAV 排后，避免为抽象而抽象
3. 执行顺序：MinerU key 网页化收尾 → P0 开源要素（git/LICENSE/Docker/单端口）→ 降 OSS 依赖

**风险**：
- MinerU 云 API 免费额度 1000 页/天，开源后使用者自备 key，需文档引导
- OSS 图片流量费由使用者自担（同地域内网 endpoint 免公网流量，既有方案可复用）
- 无鉴权是公网部署隐患，自托管必须启用可选认证
- 存储抽象过度设计风险：第一版只做 local + S3 兼容

**状态**：规划已落盘，未批准执行，不修改任何代码。


---

## 结构重建修复：阿拉伯数字章/节标题识别（2026-08-09 已执行完毕）

**背景**：b8《基础医学概论》345 章切片（真实 ~11 章），根因 RE_CH_LEVEL1 只认中文数字，
第1章/第1节（阿拉伯数字）漏判 → 误判无编号 → hash 兜底 → 所有 # 行当章。
本地复现 + 服务器实测确认。

**已做**：
- structure.py：CN_OR_AR 支持阿拉伯数字 + 第 3 章带空格变体（6 处正则 + cn_to_int）
- hash 兜底：toc 白名单为空时不再放行（宁 0 章不切片）
- 效果：b8 345→11 章，案例/问题回归正文；b7 管理学 16 章不受影响
- 服务器：预演→备份→重启→重建→OSS 外链导出（551KB 纯文本）
- git: fbe746f

---

## 表格公式渲染：门禁制转换（2026-08-10 已执行完毕）

**背景**：MinerU 表格内公式用 <eq> 标签，HTML <table> 内定界符 Typora/Obsidian 不渲染；
HTML→MD 全量转换导致列错乱（2026-08-09 多轮尝试后用户拍板回退，教训在案）。

**最终方案（用户拍板：能转的必是规整表格）**：
- 6 道质量门禁（G1 闭合配对 / G2 无 colspan·rowspan / G3 无游离文本 / G4 行列规整 / G5 2~8列·2~20行 / G6 单格≤300字符）
- 全过 → format_table_md 转 Markdown（<eq>→\$ 含实体解码、公式内 |→\vert、公式外 |→\|、表格前后空行）
- 任一不过 → 保留 MinerU HTML 原样（格式永远正确）
- 铁律：禁止为公式渲染牺牲表格格式

**实测**：《医药应用概率统计》349 表格 → 176 转（列零错乱）+ 173 保留（138 合并 + 33 超宽 + 2 超长）
**验证**：pytest 37/37 + ad-hoc 21/21 + 全量自动校验
**git**：7ea5d9b（功能）+ d9b840f（文档）

---

## 配额模型修正：优先页数 + 文件数双维度（2026-08-10 已执行完毕）

**背景**：MinerU 实测配额 = 每日**优先解析 1000 页**（优先队列快）+ 每日**总限制 5000 份文件**
（一份 PDF 算 1 份，超 1000 页进普通队列排队慢）。现状代码单维度记账（`daily_quota_pages=1000`），
`parse_book` 里 `quota.remaining() < need` 时**直接中断解析**——这是错的：MinerU 还能解析只是排队。

**目标**：优先额度不足不中断（继续解析、排队），文件数 5000 为硬上限；前端如实显示两种状态。

### 改动清单

**P0 后端**
- [x] **Q-1 config.py**：`daily_quota_pages=1000` 语义改为「每日优先页数」；新增 `daily_file_limit=5000`「每日文件数上限」
- [x] **Q-2 QuotaManager**（mineru_client.py）：quota.json 升级 `{date, priority_pages_used, files_used}`
      （旧 `{date, used}` 自动迁移）；**模块级全局锁**（routes 每次 new 实例也原子，防并发超卖，修代码评估 P1）；
      新增 add_pages / try_reserve_file / priority_remaining / files_remaining / priority_exhausted
- [x] **Q-3 parse_book**：删「优先页数不足即 break」；改为「文件数超限才 break」；
      每本 PDF 首次实际调用 API 时原子占 1 份（计数口径实测：API 响应无配额字段 → 按 PDF 去重记账，
      books 表 quota_files 列持久化，续跑不重复计）
- [x] **Q-4 /api/quota**：返回 priority 与 file 双维度 + priority_exhausted；保留旧字段兼容前端过渡

**P0 前端**
- [x] **Q-5 App.vue 徽标**：`优先配额 X/1000`；超限变 amber `⚠ 已进入普通队列（较慢）`；文件数 `文件 X/5000`
- [x] **Q-6 UploadPanel.vue**：文件数满前端拦截提示「明天再试」；超优先提示「解析进入普通队列，会较慢」

**P1 测试/文档**
- [x] **Q-7 tests/test_quota.py**（10 用例）：双维度记账 / 跨日重置 / 旧结构迁移 / 并发安全（30 线程+10 抢 3 名额）/
      parse_book 超限逻辑（mock）/ api 字段
- [x] **Q-8 前端 npm run build 验证**（gzip 29.8KB）
- [x] **Q-9 README / TODO / .env.example 配额文案更新**

**验证（2026-08-10）**：pytest 47/47（含 10 个新配额用例）+ 前端 build（gzip 29.8KB）+
uvicorn 实测 /api/quota 双维度字段 + ad-hoc 行为验证 7 项全过

---

## 前端左右不对等布局改版（2026-08-10 规划，待批准）

**目标**：单栏 880px 改为「左窄右宽」双栏——左侧边栏集中解析任务/限额/进度；
右侧主区保留上传+教材列表，底部预留「文件对比预览」占位（未来功能，本次不做）。

### 布局草图

```
┌─────────────────────────────────────────────────────────┐
│ header nav（sticky：品牌 + 状态徽标，与现在一致）           │
├───────────────┬─────────────────────────────────────────┤
│ aside 左栏     │ main 右栏（flex:1）                      │
│ 280px 固定     │                                         │
│               │ ┌─────────────────────────────────────┐ │
│ ┌───────────┐ │ │ 上传教材 PDF（现有上传卡片）            │ │
│ │ 限额面板    │ │ └─────────────────────────────────────┘ │
│ │ 优先配额 X/1000 │ ┌─────────────────────────────────────┐ │
│ │ (进度条,超限amber) │ 已入库教材（现有 book-card 列表）      │ │
│ │ 文件 X/5000 │ │ └─────────────────────────────────────┘ │
│ └───────────┘ │ ┌─────────────────────────────────────┐ │
│ ┌───────────┐ │ │ 🔍 文件对比预览（规划中，虚线占位）      │ │
│ │ 解析任务    │ │ │ 未来：原文 vs 重建后 / 导出产物对比      │ │
│ │ · 进行中:书名│ │ └─────────────────────────────────────┘ │
│ │  进度条+批次 │ │                                         │
│ │ · 待解析/失败│ │                                         │
│ └───────────┘ │                                         │
└───────────────┴─────────────────────────────────────────┘
```

### 改动清单

**P0 布局骨架**
- [x] **L-1 App.vue**：`.page` 内改 `.layout`（flex，max-width 1080px，gap 24px）+
      `<aside>`（260px 固定，sticky）+ `<main>`（flex:1）；header 保留
- [x] **L-2 style.css**：新增 `.layout`/`.sidebar`/`.content` 布局类 + 侧栏卡片样式 +
      响应式（<768px 侧栏折叠为顶部区块，单列堆叠）

**P0 左侧边栏**
- [x] **L-3 新组件 SidebarPanel.vue**（props: books/quota/settings/parseTask）：
      - 限额卡片：优先配额 X/1000 进度条（超限变 amber + 「已进普通队列（较慢）」）、
        文件 X/5000、未配 key 提示
      - 任务卡片：解析中的书（书名 + 批次进度条 + 百分比）、待解析/失败书快捷「开始解析」、
        无任务空状态「暂无解析任务」；解析消息（启动/轮询失败/完成）卡片级展示
- [x] **L-4 解析轮询逻辑上移**：UploadPanel 的 parsingId/progress/schedulePoll 提取到
      composable useParseTask.js（App 持有，reactive 返回），边栏与上传区共用同一进度源；
      自动接管「解析中」的书（刷新页面恢复轮询）保留

**P0 右侧主区**
- [x] **L-5 UploadPanel.vue**：删除内部进度条（挪到边栏任务卡片）；上传区 + 教材列表保留；
      「开始解析」触发后进度显示在左侧任务卡片；上传卡片底部加配额策略横幅（借鉴 MinerU）
- [x] **L-6 对比预览占位**：右侧底部 `<section class="card placeholder">` 虚线边框 +
      「🔍 文件对比预览（规划中）—— 未来支持原始/重建/导出产物对比」，无交互

**P1 验证**
- [x] **L-7 前端 npm run build + 冒烟**：build 通过（gzip 30.84KB）；起后端 + vite preview
      实测页面 200 / 新 JS/CSS 资源 200 / /api/health /api/quota /api/books 正常
- [x] **L-8 回归**：代码审查（parseMsg 全分支可见、.side-card h3 特异性、.page 残留清零）；
      后端 API 全通；功能回归（上传/解析/导入/删除/章节下拉逻辑未动）

### 决策点（2026-08-11 已定）
1. 左栏宽度：**260px**（参考 MinerU 侧边栏紧凑宽度；280px 偏宽、320px 太宽）
2. 教材列表归属：**右侧主区**（左侧纯状态栏，与规划推荐一致）
3. 对比预览占位：**右侧底部一个卡片**（不放顶部标题区）

### 风险
- 轮询逻辑上移改动较大，回归重点：解析进度实时性、刷新页面恢复轮询
- 本次**不做**对比预览功能本身（仅布局占位）
- 不引入新依赖，保持 Vercel token 风格

**附带（顺带，低风险）**：routes.py `structure.run` 的 `except Exception: pass` → `logger.exception`
+ 解析线程 try/except（代码评估 P0 最小项，改解析链路时顺手）

### 执行顺序
1. 实测确认文件计数口径（优先查 SDK/API 文档；必要时本地测试 token 提交 2 批看账号计数，烧 2 次调用）
2. Q-1~Q-4 后端 → pytest 全绿
3. Q-5~Q-6 前端 → npm run build
4. Q-7~Q-9 测试与文档
5. 生产部署待用户指示（本地验证通过后）

### 风险
- 旧 quota.json 迁移失败：删文件重新记账（最坏多烧 1000 页优先额度）
- 文件计数口径不确定：实测后校准 add_file 语义
- **本次不做**：前端轮询 try/catch 重构、解析任务队列化（另开任务）

---

## 代码体检修复批次（2026-08-11 已执行完毕）

**背景**：全量代码检查发现硬编码残留/死代码/边界健壮性问题，一次修完（A 组）。

### 改动清单

- [x] **A1 structure.py 硬编码书名**：rebuild() 新增 book_title 参数（默认 ''），structure.json 的 book 字段不再写死「医药应用概率统计（种子批次）」；run() 传入真实书名
- [x] **A2 清理空实现/死代码**：删 _merge_subheadings（空转）、estimate_chapter_pages（无人调用）
- [x] **A3 文件名 sanitize**：新增 routes._safe_stem（取 basename + 去扩展名 + 替换非法字符，手动处理避免 WindowsPath 吞 drive 前缀）；
      上传落盘名 / title / 导出 zip 文件名统一 sanitize；export_zip 内部对 md_name 加 _sanitize_filename 防御（双保险堵 zip slip）
- [x] **A4 上传大小上限**：流式写入统计，超 200MB 删文件报 413（不落假数据）
- [x] **A5 前端健壮性**：poll() 加 try/catch + AbortSignal.timeout(15s)，后端重启不中断轮询自动重试；
      「解析完成」文案兼容 structure_ok；App.vue 新增「后端未连接」红色徽标（原 catch 静默）
- [x] **A6 前端死依赖清理**：移除 katex / marked / markdown-it / markdown-it-texmath（去 RAG 化后零引用）；
      package.json 只剩 vue，npm run build 通过（gzip 29.93KB）
- [x] **A7 删除教材清理 OSS 孤儿图片**：OssImageUploader.delete_prefix（list + batch_delete，1000/批）；
      DELETE /api/books/{id} best-effort 清理 <书名>/images/ 前缀（无权限/网络故障仅记日志，不阻塞删除），响应新增 oss_removed 字段
- [x] **A8 文档/去重**：README 测试数 37→47；删 routes._ensure_column（db.init_db 已有迁移）、函数内重复 import shutil

### 验证（2026-08-11）
- [x] pytest 47/47 全绿
- [x] ad-hoc 行为验证 14/14（rebuild book 字段 / 死代码已删 / sanitize 5 场景 / 大小常量 / delete_prefix 存在）
- [x] 前端 npm run build 通过（gzip 29.93KB）
- [x] 已知限制：旧库中 title 含非法字符的教材，导出时已按 basename 安全化；OSS 清理仅覆盖 key 前缀 <书名>/images/，历史遗留其他前缀需人工清理


---

## 无章节兜底导入（2026-08-11 已执行完毕，生产问题 2 解决）

**背景**：论文/单篇资料等无章节文件无法走 import-obsidian（export_obsidian_zip 对 chapters 为空直接报错）；
顺带覆盖「极少数教材缺 structure.json 导入报错」已知限制。

**改动**（exporter.py）：
- [x] FB-1 _merge_raw_batches：合并全部批次原始 md（带批次页注释），作为兜底正文
- [x] FB-2 _fallback_full_chapter：构造「全文」章节（level 1，page_range=pages_covered）
- [x] FB-3 export_obsidian_zip：structure.json 缺失或 chapters 为空 → 整本一个「全文」章节，
      不再 FileNotFoundError / ValueError；local 与 oss 图模式均走同一章节管线（zip 结构 01_全文/全文.md + MOC 链接）
- [x] FB-4 测试：tests/test_fallback.py 7 用例（空章节兜底 / 缺 structure 兜底 / oss 模式无图落盘 /
      _safe_stem 6 场景 / export_zip md_name sanitize）

**验证（2026-08-11）**：pytest 54/54 全绿（47 旧 + 7 新）
**README**：已知限制两条已更新（无章节导入已支持；缺 structure.json 报错已消除）
