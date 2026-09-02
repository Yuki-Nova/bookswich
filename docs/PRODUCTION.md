# 生产变更记录（bookswich）

每次生产变更在此追加一条。**绝不记录**：密码、token、OSS secret、ssh 凭据。

记录字段：
- 变更原因
- 代码版本（git commit / 部署 tar 名）
- 是否重建教材
- 是否重导 vault
- 验证结果
- 已知例外

---

## 2026-08-18 — U 表格大一统（全 HTML）+ 线上 5 本 vault 重导

- **变更原因**：消灭表格"转 MD vs 保 HTML"的黑箱/复杂性；HTML 表借助 Obsidian html-table-math 插件
  兼顾「结构保真（含合并）+ 公式渲染」，统一为全 HTML 交付
- **代码版本**：`feat(export): 表格大一统全HTML (tables 参数)` 提交
- **是否重建教材**：否（structure 逻辑未变，仅导出层表格模式）
- **是否重导 vault**：是（线上 5 本重导为全 HTML）
- **验证结果**：pytest 176 / 本地 b1 349 表 100% HTML / `<eq>`=0 / `$` 配对 / 138 合并表结构无损；
  服务器实例健康检查绿
- **已知例外**：⭐ **Obsidian 侧需安装 html-table-math 插件**（社区插件，MIT）才有 HTML 表内公式渲染；
  服务器 vault 是纯文本，插件在用户的 Obsidian 客户端安装即对所有笔记生效

## 2026-08-18 — B 生产可靠性 + C 验证体系

- **变更原因**：生产加固（SQLite 并发/解析重试/孤儿清理/OSS 部分失败）+ 访问控制落地 + 验证体系建立
- **代码版本**：本地 commit c594ada 之后一批未提交改动；部署 tar `backend-app-20260818b5a.tgz` / `frontend-dist-20260818b5a.tgz`
- **是否重建教材**：否（structure 逻辑未变，仅导出/扫描/鉴权）
- **是否重导 vault**：否（vault 内容未受影响）
- **验证结果**：
  - 后端 pytest 172 / 前端 vitest 11 / build ✓
  - Playwright 冒烟 6/6（登录流程端到端）
  - 部署后健康检查全绿（服务/后端+token 200/首页 200/匿名 401/登录后 200/数据库 5 本/WebDAV 健康）
  - 服务器备份清理：删 2 份旧备份，释放 ~4MB，保留最新 3 份
- **已知例外**：
  - b6 分析化学 `missing_image` ×18 为 MinerU 重跑 hash 失效（历史已知，非错误）
  - nginx `auth_basic` 在宝塔 nginx 1.18 不可用（放行后 500）→ 改前端登录方案 A
  - wsgidav 使用独立认证（obsidian 账号），前端登录不涉及其它服务

## 2026-08-17 — A5 生产重导 + 表格净化链上线

- **变更原因**：A 阶段表格公式策略定案后，重导全部教材以应用 `format_table_md` 单元格净化链
- **代码版本**：本地 export/结构重建产物 + 服务器重导
- **是否重建教材**：部分（b1/b6/b8 等 structure 未变，重导出）
- **是否重导 vault**：是（5 本重 import-obsidian，OSS 外链模式）
- **验证结果**：A1 表格空行修复在服务器 5 本新导入 0 残留；旧 b1 10/20 章残留为历史导入遗留
- **已知例外**：b6 missing_image（MinerU hash）

---

## 2026-08-30 — 移除 RAG 遗留 vectors_dir（config.py）

- **变更原因**：去 RAG 化后的残留——`ensure_dirs` 仍创建 `data/vectors/` 空目录（RAG 遗迹），本次移除
- **代码版本**：commit `9d49ba6`（chore: remove RAG-era vectors_dir）
- **是否重建教材**：否
- **是否重导 vault**：否
- **验证结果**：本地 pytest **188 passed** 零回归；部署后 config.py vectors 引用 0 / systemd active / 首页 200 / `/api/health` 401（鉴权中间件正常）/ 服务器 `data/vectors` 空目录已删
- **已知例外**：无（部署前已备份服务器 config.py → `config.py.bak_20260830_p12`）

## 2026-09-02 — structure.py 结构重建双缺陷修复（b16/b17 重跑）

- **变更原因**：P0-5 目录驱动逻辑首次实战连翻两本书——①b16 药物分析化学（阿拉伯数字分章 + hash 风格）
  `kind="ar"` 章标题被 hash 目录白名单误杀（toc 白名单是去编号标题，带编号比对必失败）→ 1~15 章全降级
  进 pre_matter，384KB 正文被丢；②b17 民法学目录 OCR 把「第二章 人格权法」识别成「第二节 人格权法」
  → 目录白名单缺章 → 真章被 `_toc_match` 当伪章吞掉。另修 b16 书末「习题解答」区按章分组的重复 ar
  标题（含 OCR 变体「紫外一可见」vs「紫外—可见」）在修复①后变伪章的问题
- **代码版本**：本地 commit（本次提交，`fix(structure): ...`）；服务器直接 SFTP 覆盖
  `backend/app/services/structure.py`，备份 `structure.py.bak-20260902`（原版）与 `structure.py.bak-20260902-c5`
- **是否重建教材**：是——服务器重跑 b16/b17 结构重建（data/build/ 覆盖，未重新调用 MinerU、未耗配额）
- **是否重导 vault**：否（导出产物待用户按需重导）
- **验证结果**：
  - 本地 pytest **194 passed** / b1 概率统计重建 11 章序列一致零回归
  - 服务器 chapters API：b16 **18 章**（1~15+16 无编号+17+18）、b17 **7 章**（含补锚 第二/六章）、
    b13 管理学 16 章回归不变；outline.md 章节树完整、2 条补锚 warning 符合预期；服务 active、py_compile OK
- **已知例外**：补锚容错与「正文引用条文」伪章过滤靠三层保守条件（行首 # + 标题长度 2~30 + 章号序进
  + 非引号/非「共 N 条」）平衡，极端情况下目录漏录且正文标题带引号的真章仍可能无法补锚
