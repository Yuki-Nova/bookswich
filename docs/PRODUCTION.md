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
