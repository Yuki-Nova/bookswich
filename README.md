# bookswich · 教材 PDF → 结构化 Markdown

把教材 PDF（含读秀/超星纯扫描版）变成**结构准确、格式修正过的 Markdown**：上传 → MinerU 云解析 → 规则法+目录驱动结构重建 → 下载（整本/单章/Obsidian 版），供 Obsidian / Typora 使用。

> 2026-08-06 起已去 RAG 化：本项目只做「解析 + 格式修正 + 下载」，知识库由 **Obsidian + Hermes** 管理。

## 核心能力

### 结构重建（规则法 + 目录驱动）
- **不信任 MinerU 的 `#` 标题推断**：全部清除后按教材编号体系重新打标（第x章 → 第x节/x.y → 一、 → （一））
- **目录驱动（P0-5，2026-08-16）**：从「## 目录」锚点提取章节条目（页码 OCR 丢失容忍），
  目录区域整段跳过 + 正文「第x章」必须命中目录白名单并按目录顺序锚定——目录残渣、正文引用的法规条文、
  附录条文等伪章全部被过滤（实测 b11 药事法 30 章误判 → 10 真章）
- 目录有页码时章节 `page_range` 用真实页码（p121）；hash 风格/无目录教材自动回退旧规则

### 表格策略（2026-08-18 U 大一统：全 HTML）
- **默认全 HTML**：所有表格保留原生 HTML——结构 100% 保真（含合并单元格/宽表），表内公式以 `$..$` 定界符输出，
  由 Obsidian 社区插件 **html-table-math** 渲染（需在 vault `.obsidian/plugins/` 安装）
- **可选 MD 模式**（`tables="md"`，旧门禁转换保留在函数签名，不默认执行）：6 道门禁通过才转 Markdown 表格，
  未通过保留 HTML；适合不使用插件、需原生 MD 表的场景
- **单元格公式净化（2026-08-17）**：实体解码 → 公式间双空格压平（`$A$  $B$`→`$A$ $B$`）→ 定界符净化 → 竖线转义
  （公式内 `|`→`\vert`，公式外 `|`→`\|`，条件概率 P(A|B) 不切断表格列）——全 HTML 与 MD 路径统一受益
- 实测 b1（全 HTML 默认，2026-08-18）：349 表 **100% HTML**、`<eq>` 残=0、`$` 配对、138 合并表结构无损、161 表公式可渲染

### 导出深度清洗（2026-08-16 借鉴 mineru-tianshu）
- 双层 HTML 反转义（`&amp;gt;`→`>`）+ 删 `<del>` 幻觉标签 + 空行折叠
- `<img>` 标签图片引用归一化为 Markdown 语法，打包/统计链路 IMG_RE 双语法兼容
- 表格内容绝不参与清洗（用户决策：MinerU 的表格零改动）

### 图片与分发
- 图片随解析落盘，导出 zip 只打包实际引用（md + images/ 同级，解压即 Obsidian/Typora 可读）
- `images=oss`：图片传阿里云 OSS（hash 幂等），md 引用改公网 URL，**vault 只落文本**（多端同步轻量）
- Obsidian 版：按章拆分 + `00_总览.md` MOC（[[双链]] 导航）+ 无章节教材「全文」兜底
- **import-obsidian 幂等**：解压前清理同名旧目录（防新旧结构并存污染 vault）

## 快速开始

### 一键启动（推荐）
```powershell
.\start.ps1            # 启动前后端并打开浏览器
.\start.ps1 -Restart   # 先停旧服务再启动
.\stop.ps1             # 停止服务
```

### 环境要求
- Python 3.10+ / Node.js 18+
- MinerU 云 API Key（[获取](https://mineru.net)）

### 手动启动
```powershell
# 后端（backend/ 目录）
uv venv .venv --python python
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
Copy-Item .env.example .env        # 填 MINERU_API_KEY（可选 OSS/Obsidian 配置）
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端（frontend/ 目录，另开终端）
npm install                          # 慢可加 --registry=https://registry.npmmirror.com
npm run dev                          # http://localhost:5173
```

### 使用流程
1. **上传** PDF → 自动检测页数 → 开始解析（分批 25 页，进度条 + 配额显示）
2. 解析完成后**自动结构重建**（目录驱动，秒级）
3. **下载**：整本/单章/原始版 zip（`书名.md` + `images/`，解压即用）
4. **导入 Obsidian**（推荐，WebDAV 同步方案）：配置 `OBSIDIAN_VAULT_DIR` 后网页点「导入 Obsidian」→ 写入 vault 教材目录，Obsidian Remotely Save 自动同步；图片转 OSS 外链，vault 只存文本

## API 一览（prefix /api）

| 接口 | 说明 |
|------|------|
| `POST /books/upload` | multipart 上传 PDF（200MB 上限，PyMuPDF 自动检测页数） |
| `POST /books/{id}/parse` | 后台分批解析（进度轮询 GET /books/{id}） |
| `GET /books/{id}/chapters` | 章节列表（结构重建产物） |
| `GET /books/{id}/compare` | 解析质检报告（表格门禁原因分布/图片缺失/警告） |
| `GET /books/{id}/compare/chapter/{n}?as=diff\|markdown` | 按章 raw vs rebuilt 行级 diff |
| `GET /books/{id}/export?format=rebuilt\|raw\|obsidian&chapter=N&images=local\|oss` | 导出 ZIP |
| `POST /books/{id}/import-obsidian` | 按章导入 vault（幂等，OSS 外链） |
| `GET /quota` | MinerU 配额（页数 + 文件数双维度） |

## 技术栈

| 环节 | 选型 |
|------|------|
| 后端 | Python FastAPI（uvicorn，127.0.0.1:8000） |
| 前端 | Vue 3 + Vite + KaTeX（暗色工作台风格） |
| 解析 | MinerU 云 API（分批 25 页，落盘缓存 + 图片落盘 + 配额记账） |
| 存储 | SQLite（data/kb.db，仅 books 元数据） |

## 项目结构

```
bookswich/
├── backend/
│   ├── app/
│   │   ├── main.py              # 入口：CORS + 可选 API_TOKEN 鉴权 + lifespan
│   │   ├── api/routes.py        # REST 接口
│   │   └── services/
│   │       ├── mineru_client.py # 分批解析 + 缓存完整性 + 配额
│   │       ├── structure.py     # 规则法+目录驱动重建（核心）
│   │       ├── exporter.py      # 导出 + 表格门禁/净化链 + 深度清洗
│   │       ├── verify_export.py # 导出物静态回归扫描（A4）
│   │       ├── audit_orphans.py # 孤儿产物只读审计（B3）
│   │       ├── compare.py       # 质检报告 + 按章 diff
│   │       └── oss_images.py    # OSS 图片上传（幂等 + 部分失败处理 B4）
│   └── tests/                   # pytest 175 用例
├── frontend/src/                # Vue 3 单页（上传/进度/下载/对比）
├── data/                        # raw/ + md/<book>/ + build/<book>/ + kb.db + quota.json
├── export/                      # 已导出 Markdown
└── docs/                        # TODO.md（方案/里程碑）+ TECH.md（技术文档）
```

## 测试

```powershell
cd backend
.venv\Scripts\python.exe -m pytest    # 175 用例全绿
cd ../frontend
npm test                              # vitest 18 用例
npm run verify:build                  # 前端构建门禁（vite build + 产物检查）
```

## 生产部署（阿里云 ECS）

- 后端：systemd `bookswich.service`，uvicorn 127.0.0.1:8001（nginx 反代 bookswich.yukinova.top）
- 前端：`frontend/dist` 由 nginx 托管；WebDAV vault：wsgidav 8081（webdav.yukinova.top，Obsidian 同步）
- **访问控制（2026-08-18 启用，前端登录方案 A）**：后端 `web_password` 签发会话 token，`POST /api/auth/login` 登录；
  前端登录页 + `authFetch` 统一带 `X-Auth-Token`。`/api` 匿名 401、登录后 200；`api_token`（程序）仍可用。
  首页静态公开（SPA 壳）；nginx `auth_basic` 因宝塔 nginx 1.18 该模块不可用未采用（见 docs/TECH.md §1.6）
- 部署流程见 skill `bookswich-deploy`（paramiko 打包上传 → 备份 → 解压 → 重启 → 验证）

## 已知限制

- 极少数 OCR 截断的残缺公式无法自动修复（导出后 Typora 显示为原文）
- MinerU 偶发缺个别图片（导出 zip 跳过该引用，其余图片正常；重跑批次可补图）
- 保留 HTML 的表格（合并单元格等）内公式渲染取决于渲染器对 HTML 内 inline math 的支持——
  2026-08-18 已修复表格前后空行边界问题；规整表格经门禁转 MD 后公式可渲染。复杂表格
  维持 HTML 原样为**已决策略**（2026-08-18 依据 3 本教材 576 表统计：被拦公式表主因是
  合并单元格，非合并被拦者全为超宽/超长格，局部转换收益不抵风险，见 docs/TODO.md A3）
- 知识库管理已移交 Obsidian（本项目不再提供问答）

## 未来规划

- **Obsidian 教材导入插件（P2 远期）**：在 Obsidian 内直接「导入 PDF → 解析 → 生成 vault 笔记」（详见 docs/TODO.md）

---

> 测试样本：《医药应用概率统计》第 3 版（369 页纯扫描版）、《工业药剂学》等 6 本教材已完整解析并导入 vault
