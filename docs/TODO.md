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

## 当前执行规划

完整设计、修改范围、验收标准和依赖关系见：
`.hermes/plans/2026-08-18_120000-bookswich-roadmap.md`。

执行原则：先修明确质量问题，再补生产可靠性与验证体系，最后评估远期能力。
复杂 HTML 表格继续以格式忠实为第一原则，禁止未经真实教材验证就放宽门禁。

### A. 交付质量收尾（当前阶段）

- [x] **A1 / P0** 修复 HTML 表格与 Markdown 标题边界（2026-08-18 完成）
  - `_node_to_md` 的 HTML 保留路径增加稳定的前后空行（与 `format_table_md` 对称）
  - HTML 内容和属性零改动，仅允许标签间排版换行；`\n{3,}` 折叠不吞边界
  - 回归测试 `tests/test_html_boundary.py`（5 用例）；全量 pytest 123 通过
- [x] **A2 / P0** 统计真实教材中 HTML 表格公式分布（2026-08-18 完成）
  - `compare._table_stats` 增加 math 维度（`_is_math_table` 保守判定：$ 定界符 / `<eq>` / LaTeX 命令）
  - 新增 `scripts/audit_tables.py`（只读审计，人类可读 + `--json`），测试 +4 用例
  - 3 本真实教材统计（b1 概率统计 / b6 分析化学 / b8 工业药剂学；b11 药事法无本地 build，
    以 b6 补位）：总表 576，公式表 248（43.1%），其中转 MD 144（58.1%）、保留 104（41.9%）
- [x] **A3 / P0-P1** 决策：**维持保留 HTML，不实现局部转换**（2026-08-18，依据 A2 数据）
  - 保留公式表拦截原因：merged 占绝对主因（b1 74/82、b6 16/17、b8 5/5）——Markdown 无合并
    语义，转换必须放弃合并（被禁）
  - 非合并被拦公式表极少（b1 8、b6 1、b8 0），且全为 cols≥9 超宽列 / 单格 >300 字符
    （样例核对：频数分布表、函数值表、算法步骤表）——转 MD 会列溢出/单格爆炸，收益
    （公式渲染）不抵风险；G5/G6 拦截是正确行为非误伤
  - 已转 MD 公式表 144 个已获公式渲染；剩余 104 个保留 HTML，接受渲染器限制（已知限制）
- [x] **A4 / P1** 建立导出物专项扫描（2026-08-18 完成）
  - `app/services/verify_export.py` 8 规则（img/del 残影、异常空行、坏公式定界符、
    表格粘连、缺图、MD/HTML 行列一致性）+ `scripts/verify_export.py` CLI（JSON 输出）
  - 表格内允许项不误报（约定 #1）；规则表与用法见 TECH.md §1.4；测试 22 用例
  - b1 全书 rebuilt 导出（1140KB）实测扫描零 issue
- [x] **A5 / P0** 重建并体检全部真实教材（2026-08-18 完成）
  - 本地 3 本（b1/b6/b8 工业药剂学）新代码导出 + verify_export 扫描：
    b1 零 issue、b8 零 issue、b6 仅 18 张 MinerU 历史缺图（重跑 hash 失效，已知例外）
  - 顺带修复：`format_table_md` 单元格内 `<img>` 归一化为 `![]()`（A5 实测 b6 暴露，+1 用例）
  - 部署新代码至服务器（app.bak-20260818/dist.bak-20260818 备份保留）
  - 服务器 5 本重导 OSS 导入 vault：files=章+1 验证通过；清理 `扩展教材/* 1` 旧目录残留；
    工业药剂学/药事法按用户布局移回 扩展教材/
  - vault 全量体检（6 本）：章目录=structure 章数、00_总览、无 images 目录（OSS 纯文本）、
    非 md 文件 0、旧目录残留 0、图片全 OSS 外链、无奇数 $ 行 —— 全过
  - A1 线上对照验证：42 个含表格 md 中，5 本新重导 0 边界残留；唯一残留（b1 概率统计 10 个 md）
    为 8-17 旧导入，服务器无该教材源数据无法重导，记录为已知例外

### B. 生产可靠性

- [x] **B1 / P1** SQLite `busy_timeout` 30s + WAL 模式；并发压力/进度更新/旧库迁移测试（2026-08-18）
  - `get_conn` 加 `timeout=30` + `PRAGMA busy_timeout=30000`；`init_db` `PRAGMA journal_mode=WAL`
  - `tests/test_db_concurrency.py`（5 用例）：8 线程×30 读写无锁、进度短事务、旧库迁移
- [x] **B2 / P1** 解析异常分类、有限重试、可读失败原因（2026-08-18）
  - `mineru_client.parse_book`：网络类异常（ConnectionError/Timeout/OSError）重试 2 次（指数退避），
    业务失败（云端返回 error）不重试；books 表新增 `parse_error` 列
  - `routes.start_parse._run`：失败写可读 parse_error，崩溃兜底写「解析线程崩溃」
  - `tests/test_parse_failure.py`（8 用例）：瞬态重试成功 / 超限失败 / 业务不重试 / 可读错误 / 重试 / 并发拒绝 / 重启恢复
- [x] **B3 / P1** 文件生命周期 + 孤儿产物 dry-run 清理（2026-08-18）
  - `services/audit_orphans.py`：DB vs 磁盘目录差异（孤儿/缺失）、未引用图片识别（跨批共享目录按 md 引用判定）
  - `scripts/audit_orphans.py` CLI：只读报告 / `--dry-run` / `--delete`（默认 dry-run）
  - `tests/test_audit_orphans.py`（5 用例）；真实扫描：b8 工业药剂学 267 孤儿图（8.3MB，MinerU 重跑残留）
- [x] **B4 / P1** OSS 失败/部分成功 + 本地降级（2026-08-18）
  - `upload_many` 返回 `(mapping, failed)`：单图失败入清单不影响其它；源缺失跳过；幂等已存在不失败
  - `_to_oss_links`：失败图不写 URL（保持相对路径），不产生错误公网链接
  - `tests/test_oss_failure.py`（6 用例）；`image_mode=local` 不依赖 OSS
- [x] **B5 / P1** 生产访问控制（2026-08-18 落地，前端登录方案 A）
  - **诊断**：宝塔 nginx 1.18 `auth_basic` 模块不可用（放行后 500，错误密码也 500；已作对照实验确诊）
  - **落地（方案 A）**：后端 `app/services/auth.py`（api_token 程序 + web_password 会话 token 双通道校验）+ `POST /api/auth/login`
    签发 token；前端 `auth.js`（authFetch 统一带 X-Auth-Token + authedUrl 供 download/图片链接）+ `LoginPanel.vue` 登录页 +
    App.vue 登录态 + 各调用点接入。`.env` 配 `web_password`（登录密码）
  - **已验证**：匿名 /api 401；登录拿 token；带 token books/health 200；错密码 401；首页静态 200（SPA 壳公开）
  - **测试**：`tests/test_auth.py`（6 用例）；后端 pytest 157、前端 build 通过

### C. 验证体系

- [x] **C1 / P1** 后端接口回归（2026-08-18）
  - `tests/test_api_regression.py`（13 用例）：upload 非 PDF/损坏/有效、export 非法 format/images/raw+chapter/章节越界、
    oss 未配置、删除解析中/不存在/成功。全量 pytest 172
- [x] **C2 / P1** 前端 composable + auth 行为测试（2026-08-18，引入 vitest）
  - `package.json` 加 `test=vitest run` + devDeps vitest/@vue/test-utils/jsdom
  - `src/composables/useParseTask.test.js`（4 用例）：文件配额拦截/startParse/解析中接管/完成清理
  - `src/__tests__/auth.test.js`（7 用例）：token 存取/authFetch 注入 X-Auth-Token/401 清理/authedUrl；全量 vitest 11 通过
- [x] **C3 / P1** Playwright 核心流程冒烟（2026-08-18，含 B5-A 登录）
  - 线上站点验证：登录页显示、错误密码报错、正确密码登录渲染主界面、教材列表加载（服务器真实数据）、
    token 存 localStorage（len 52）、刷新登录态保持、无 5xx —— 6/6 通过，截图 export/shots/
- [x] **C4 / P1** 真实教材黄金样本固化（2026-08-18）
  - `scripts/golden_samples.py`：采集本地 build 教材章数/标题 → 固化 `data/build_golden_samples.json` 基线，
    `--update` 更新 / 默认校验（3 本全过，无退化）
  - `tests/test_golden_samples.py`（2 用例）：校验通过 + 基线非空（结构/导出规则修改后重跑防退化）
- [ ] **C5 / P2** 增加构建产物、console error、pageerror 和 HTTP 5xx 门禁

### D. 运维自动化

- [x] **D1 / P2** 教材重建/重导命令（2026-08-18）
  - `scripts/ops.py`：`rebuild / export / import` 子命令，`--id/--title/--out/--dry-run`；书名必须显式传入（不硬编码）
- [x] **D2 / P2** vault 体检命令（2026-08-18）
  - `scripts/vault_health.py`：教材目录/章节数（对照左侧 structure）、MOC 链接、图片 OSS 引用、
    残留 HTML/实体/坏公式/异常空行、孤儿 md；`--json` 机器可读；`scan_dir(structure_dir=None)` 兼容无结构书
- [x] **D3 / P2** 服务器备份清理（2026-08-18）
  - `scripts/server_health.py --cleanup`：列出现有备份、保留最新 3 份、先 dry-run 列将删再 `--apply`；
    记录清理时间/数量/释放空间到 `scripts/backup_cleanup.log`；实测删 2 份旧 dist.bak 释放 ~4MB
- [x] **D4 / P2** 部署后健康检查（2026-08-18）
  - `scripts/server_health.py --check`：服务状态/后端直连+token/前端首页/api 匿名 401/登录后 200/数据库可读/WebDAV 监听——全绿
- [x] **D5 / P2** 版本化生产变更记录（2026-08-18）
  - `docs/PRODUCTION.md`：模板（原因/版本/是否重建/是否重导/验证/例外）+ 2026-08-18 与 08-17 两条记录；
    明确不记录密码/token/secret

### E. 远期能力

- [ ] **E1 / P2** 生成章节知识点 Markdown 大纲，不引入 RAG 或向量库
- [ ] **E2 / P2** 增强公式/表格质检和章节问题定位，优先报告而非自动改写
- [ ] **E3 / P2** 预研 Obsidian 导入插件；插件只调用现有 API，不复制后端逻辑

## 推荐批次

1. **批次 1：** A1 + A4，修复明确 bug 并建立边界回归。
2. **批次 2：** A2 + A3，用真实数据决定 HTML 表格公式策略。
3. **批次 3：** A5，重建、重导并体检全部教材。
4. **批次 4：** B1-B4，完善数据库、解析、文件和 OSS 可靠性。
5. **批次 5：** C1-C4，建立后端、前端、浏览器和黄金样本验证体系。
6. **批次 6：** B5 + D1-D5，完成生产安全和运维自动化。
7. **批次 7：** E1-E3，按实际收益评估远期能力。

## 风险与对策

| 风险 | 对策 |
|------|------|
| OCR 目录页码丢失导致目录驱动失效 | 页码允许为 None，回退批次页区间；目录抽取失败回退旧逻辑 |
| 表格门禁误判或放宽后列错乱 | 门禁保持保守；先统计、再局部试验；真实教材逐表验证 |
| MinerU 输出脏数据 | 正文深度清洗，HTML 表格排除；导出物专项扫描 |
| 结构逻辑更新后 vault 仍是旧产物 | 统一执行重建、重导、vault 体检，流程保持幂等 |
| 后台解析和轮询造成 SQLite 锁冲突 | 短事务、busy timeout、WAL 评估和并发测试 |
| OSS 部分失败生成不完整笔记 | 上传结果显式分类；失败时阻止伪成功并保留本地导出 |

## 本轮完成定义

- [ ] HTML 表格标题边界问题修复并有回归测试
- [ ] HTML 表格公式问题有真实统计和明确产品决策
- [ ] 五本以上真实教材重建、导出、导入无结构退化
- [ ] pytest、前端 build、Playwright 冒烟全部通过
- [ ] 解析失败不会永久停留在 `parsing`
- [ ] SQLite 并发和 OSS 失败路径经过验证
- [ ] 生产站点具有整站访问控制
- [ ] 重建、重导和 vault 体检可以重复执行
- [ ] `README.md`、`docs/TODO.md`、`docs/TECH.md` 与实际行为一致

## 明确不做

- 不恢复 RAG、向量检索或问答服务
- 不全量强制 HTML 表格转 Markdown
- 不为清洗效果删除可能具有数学语义的 LaTeX
- 不在 Obsidian 插件中复制解析、结构重建或导出逻辑
- 不在缺少真实教材验证时修改表格门禁阈值
