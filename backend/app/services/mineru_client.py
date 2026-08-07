"""MinerU 解析服务：分批解析 + 落盘缓存 + 配额记账。

- 完整模式：有 MINERU_API_KEY 时用 extract_batch（600 页/文件上限）
- Flash 模式：无 key 时用 flash_extract（20 页 / 10MB 限制，用于小批量测试）
- 每日配额记账（MinerU 云 API 免费额度 1000 页/天）
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Callable

from ..config import settings

FLASH_MAX_PAGES = 20


class QuotaManager:
    """每日配额记账，数据落盘 data/quota.json。"""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else settings.quota_file

    def _load(self) -> dict:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("date") == date.today().isoformat():
                    return data
            except Exception:
                pass
        return {"date": date.today().isoformat(), "used": 0}

    def used_today(self) -> int:
        return int(self._load().get("used", 0))

    def remaining(self) -> int:
        return max(settings.daily_quota_pages - self.used_today(), 0)

    def add(self, pages: int) -> int:
        data = self._load()
        data["used"] = int(data.get("used", 0)) + int(pages)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return int(data["used"])


class MineruParser:
    """MinerU 云 API 封装。"""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.mineru_api_key
        self.quota = QuotaManager()

    def _extract(self, pdf_path: str, pages: str) -> dict:
        """解析指定页范围，返回 {markdown, content_list, error}。"""
        from mineru.client import FileParam, MinerU

        if self.api_key:
            # 完整模式：一次最多 600 页
            with MinerU(token=self.api_key) as client:
                results = list(
                    client.extract_batch(
                        [pdf_path],
                        language="ch",
                        file_params={pdf_path: FileParam(pages=pages)},
                    )
                )
        else:
            # Flash 模式：单次最多 20 页，无需 key（测试用）
            with MinerU(token=None) as client:
                results = [client.flash_extract(pdf_path, language="ch", page_range=pages)]

        result = results[0] if results else None
        if result is None:
            return {"markdown": None, "content_list": None, "error": "no result returned"}
        if result.state == "failed":
            return {
                "markdown": None,
                "content_list": None,
                "error": result.error or "server-side parse failed",
            }
        return {
            "markdown": result.markdown,
            "content_list": result.content_list,
            "images": getattr(result, "images", None) or [],  # list[Image]，落盘时写 images/
            "error": None,
        }

    @staticmethod
    def _batch_complete(batch_file: Path) -> bool:
        """缓存完整性检查：md 存在，且该批次 content_list 引用的图片文件都已落盘。

        旧版（2026-08-06 前）只落盘 markdown 没保存图片，content_list 含 image
        但对应文件缺失 → 视为缓存不完整，重新解析以补图。
        注意：images/ 目录是所有批次共享的，不能只看目录非空（第一批重跑后
        会让后续批次误判完整）——必须逐批核对 img_path 文件是否存在。
        """
        if not batch_file.exists():
            return False
        cl_file = batch_file.with_suffix(".json")
        if cl_file.exists():
            try:
                items = json.loads(cl_file.read_text(encoding="utf-8"))
                img_names = [
                    it.get("img_path") for it in items
                    if isinstance(it, dict) and it.get("type") == "image"
                    and it.get("img_path")
                ]
                if img_names:
                    img_dir = batch_file.parent / "images"
                    missing = [
                        n for n in img_names
                        if not (img_dir / Path(n).name).exists()
                    ]
                    if missing:
                        return False
            except Exception:
                pass
        return True

    def parse_book(
        self,
        book_id: int,
        pdf_path: str,
        total_pages: int,
        book_title: str,
        batch_size: int | None = None,
        progress_cb: Callable[[int, int], None] | None = None,
    ) -> dict:
        """分批解析全书，落盘 data/md/<book>/batch_XX_pN-M.md。

        progress_cb(done_batches, total_batches) 用于回传进度。
        返回 {batch_files, batches_total, pages_used, errors, skipped_cached}
        """
        md_dir = settings.md_dir / f"b{book_id}_{book_title}"
        md_dir.mkdir(parents=True, exist_ok=True)

        if total_pages <= 0:
            raise ValueError(
                f"total_pages={total_pages} 无法分批解析（上传时页数检测失败？）"
            )

        batch_size = batch_size or settings.parse_batch_size
        if not self.api_key:
            batch_size = min(batch_size, FLASH_MAX_PAGES)

        batches = []
        for start in range(1, total_pages + 1, batch_size):
            end = min(start + batch_size - 1, total_pages)
            batches.append((start, end))

        batch_files: list[str] = []
        errors: list[str] = []
        pages_used = 0
        skipped_cached = 0

        for idx, (start, end) in enumerate(batches, 1):
            batch_file = md_dir / f"batch_{idx:02d}_p{start}-{end}.md"
            if self._batch_complete(batch_file):
                batch_files.append(str(batch_file))
                skipped_cached += 1
                if progress_cb:
                    progress_cb(idx, len(batches))
                continue

            need = end - start + 1
            if self.quota.remaining() < need:
                errors.append(f"quota_exceeded at batch {idx} (p{start}-{end})")
                break

            pages_str = f"{start}-{end}" if start != end else str(start)
            try:
                out = self._extract(str(pdf_path), pages_str)
            except Exception as exc:
                errors.append(f"batch {idx} (p{start}-{end}): {type(exc).__name__}: {exc}")
                continue

            if out["error"] or not out["markdown"]:
                errors.append(f"batch {idx} (p{start}-{end}): {out['error'] or 'empty markdown'}")
                continue

            batch_file.write_text(out["markdown"], encoding="utf-8")
            # 图片落盘到 images/ 子目录（markdown 里的 ![](images/xxx.jpg) 相对引用）
            images = out.get("images") or []
            if images:
                img_dir = batch_file.parent / "images"
                img_dir.mkdir(exist_ok=True)
                for img in images:
                    (img_dir / img.name).write_bytes(img.data)
            # content_list（若云端返回）落盘 JSON，P0-3 结构重建可能用到页码信息
            if out.get("content_list"):
                cl_file = batch_file.with_suffix(".json")
                cl_file.write_text(
                    json.dumps(out["content_list"], ensure_ascii=False, indent=1),
                    encoding="utf-8",
                )
            self.quota.add(need)
            pages_used += need
            batch_files.append(str(batch_file))
            if progress_cb:
                progress_cb(idx, len(batches))

        return {
            "batch_files": batch_files,
            "batches_total": len(batches),
            "pages_used": pages_used,
            "skipped_cached": skipped_cached,
            "errors": errors,
        }
