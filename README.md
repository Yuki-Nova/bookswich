# bookswich · 教材 PDF 解析下载工具

把教材 PDF（含纯扫描版）变成**结构清晰、格式修正过的 Markdown**：上传 → 自动解析 → 网页下载，供 Obsidian / Typora 等工具使用。

## 功能特性

- 任意 PDF 教材，上传后自动分批解析（MinerU OCR，公式转 LaTeX、表格转 HTML）
- 不信任 OCR 的标题推断，按教材编号体系（章→节→小节）重新打标，章节结构准确
- 按章拆分（每章 30~370KB 秒开，性能友好）+ MOC 总览页（[[双链]] 导航）；图片转 OSS 外链（vault 纯文本，多端同步轻量）；WebDAV 同步方案下导入即同步（无需下载）
- 提供整本 / 单章 / 原始 OCR / Obsidian 版（zip 包），一键导入obsidian选项，对Typora/Obsidian格式 友好（公式规范化、无超长行）
- **表格智能转换（2026-08-10）**：6 道质量门禁（闭合配对/无合并单元格/无游离文本/行列规整/2~8列/2~20行/单格≤300字符）通过 → HTML 表格转 Markdown 表格（表格内公式可渲染），未通过 → 保留 HTML 原样（格式永远正确）；实测 349 表 → 176 转 + 173 保，转换表列零错乱
- 实时显示MinerU 免费额度（优先 2 解析每日 1000 页；每日总限 5000 份文件，一份 PDF 无论页数均按 1 计），解析进度可视化
- 前端重设计（sticky 导航 + 拖拽上传 + 教材卡片列表 + 状态徽标）

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

### 安装与启动

```powershell
# 1. 后端
cd backend
uv venv .venv --python python          # 创建虚拟环境
uv pip install --python .venv\Scripts\python.exe -r requirements.txt   # 安装依赖（慢可加 --index-url https://pypi.tuna.tsinghua.edu.cn/simple）
Copy-Item .env.example .env            # 填入 MINERU_API_KEY
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2. 前端（另开终端）
cd frontend
npm install                            # 慢可加 --registry=https://registry.npmmirror.com
npm run dev                            # 打开 http://localhost:5173
```

### 使用流程

1. **上传**：选择 PDF → 上传 → 自动检测页数 → 开始解析（进度条 + 配额显示）
2. 解析完成后自动结构重建（约几分钟，369 页实测 15~20 分钟）
3. **下载**：教材列表点"下载 ZIP"，解压得到 `书名.md` + `images/` 文件夹，**整个文件夹**放进 Obsidian vault（md 与 images/ 须同目录）即可显示图片
4. **导入 Obsidian**（推荐，WebDAV 同步方案）：配置 `OBSIDIAN_VAULT_DIR` 后网页点「导入 Obsidian」——
   - **服务器部署**：导入直接写入 WebDAV 同步目录（如 `/srv/obsidian-vault/教材/`），Obsidian Remotely Save 自动同步，**无需下载**
   - **本地部署**：导入写入本地 vault 路径（如 `/path/to/vault/教材/`）
   - 图片全部转 OSS 外链，vault 只存文本（多端同步体积最小）

## 技术栈

| 环节 | 选型 |
|------|------|
| 后端 | Python FastAPI |
| 前端 | Vue 3 + Vite + KaTeX |
| 解析 | MinerU 云 API（分批 25 页，落盘缓存） |
| 存储 | SQLite（仅 books 教材元数据） |

## 项目结构

```
bookswich/
├── backend/            # FastAPI 后端
│   ├── app/
│   │   ├── api/routes.py       # REST 接口（books/upload/parse/chapters/export/quota）
│   │   └── services/           # mineru_client / structure / exporter
│   └── tests/                  # pytest 测试（10 用例）
├── frontend/           # Vue 3 前端（上传 + 下载）
├── data/               # 解析产物（raw/md/build/kb.db/quota.json）
├── export/             # 已导出的 Markdown 文件
└── docs/
    ├── TODO.md         # 项目方案与里程碑
    └── TECH.md         # 技术文档（架构/流程/踩坑记录）
```

## 测试

```powershell
cd backend
.venv\Scripts\python.exe -m pytest    # 37 用例全绿
```

## 文档

- [技术文档 docs/TECH.md](docs/TECH.md) —— 架构、核心流程、API、踩坑记录
- [方案与里程碑 docs/TODO.md](docs/TODO.md) —— 规划、进度、风险对策

## 已知限制

- 极少数 OCR 截断的残缺公式无法自动修复（导出后 Typora 显示为原文）
- 精确页码被目录页污染（分批区间页码可靠，精确页码待修）
- MinerU 偶发缺个别图片（导出 zip 会跳过该引用，其余图片正常）
- 知识库管理已移交 Obsidian（本项目不再提供问答）
- 无章节结构的文件（论文/单篇资料）暂不能走 Obsidian 导入（2026-08-07 记录，待支持）
- 极少数已解析教材缺结构重建产物 structure.json 时导入会报错（2026-08-07 记录，待排查）

## 未来规划

- **Obsidian 教材导入插件（P2 远期）**：在 Obsidian 内直接「导入 PDF → 解析 → 生成 vault 笔记」，解析引擎仍走 bookswich 后端（详见 docs/TODO.md OBP-1~OBP-6）

---

> 测试样本：《医药应用概率统计》第 3 版，369 页纯扫描版，已完整解析
