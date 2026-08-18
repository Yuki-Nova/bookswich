"""MinerU 解析服务：分批解析 + 落盘缓存 + 配额记账。

- 完整模式：有 MINERU_API_KEY 时用 extract_batch（600 页/文件上限）
- Flash 模式：无 key 时用 flash_extract（20 页 / 10MB 限制，用于小批量测试）
- 每日配额记账（MinerU 云 API 免费额度 1000 页/天）
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date
from pathlib import Path
from typing import Callable

from ..config import settings

logger = logging.getLogger(__name__)

FLASH_MAX_PAGES = 20

# B2 有限重试（2026-08-18）：网络类瞬时错误（连接重置/超时）尝试重试
_RETRYABLE_EXC = (ConnectionError, TimeoutError, OSError)
# 退避间隔（秒），测试可 monkeypatch 成 (0, 0) 提速
RETRY_DELAYS = (1.0, 2.0)

# 全局锁：routes 每次请求各自 new QuotaManager()，锁必须模块级共享才原子
_QUOTA_LOCK = threading.Lock()


class QuotaManager:
    """每日配额记账，数据落盘 data/quota.json。

    双维度（对应 MinerU 云 API 实际规则）：
      priority_pages_used —— 每日优先解析页数（1000 页内走优先队列，快）
      files_used          —— 每日文件数（一份 PDF 无论多少页均按 1 份计，硬上限 5000）

    旧结构 {date, used} 自动迁移：used → priority_pages_used。
    所有读改写加锁，防并发解析时配额超卖。
    """

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else settings.quota_file
        self._lock = _QUOTA_LOCK

    def _load(self) -> dict:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("date") == date.today().isoformat():
                    # 旧结构 {date, used} 迁移（惰性，下次写回时落盘新结构）
                    if "used" in data and "priority_pages_used" not in data:
                        data["priority_pages_used"] = int(data.get("used", 0))
                        data.pop("used", None)
                        data.setdefault("files_used", 0)
                    return data
            except Exception:
                pass
        return {
            "date": date.today().isoformat(),
            "priority_pages_used": 0,
            "files_used": 0,
        }

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ── 读 ─────────────────────────────────────────────

    def priority_used_today(self) -> int:
        with self._lock:
            return int(self._load().get("priority_pages_used", 0))

    def files_used_today(self) -> int:
        with self._lock:
            return int(self._load().get("files_used", 0))

    def priority_remaining(self) -> int:
        return max(settings.daily_quota_pages - self.priority_used_today(), 0)

    def files_remaining(self) -> int:
        return max(settings.daily_file_limit - self.files_used_today(), 0)

    def priority_exhausted(self) -> bool:
        return self.priority_used_today() >= settings.daily_quota_pages

    # ── 写（加锁保证 read-modify-write 原子）────────────

    def add_pages(self, pages: int) -> int:
        """累计解析页数（优先+普通都累计；超 1000 页不中断，只进普通队列）。"""
        with self._lock:
            data = self._load()
            data["priority_pages_used"] = (
                int(data.get("priority_pages_used", 0)) + int(pages)
            )
            self._save(data)
            return int(data["priority_pages_used"])

    def try_reserve_file(self) -> bool:
        """原子尝试占用 1 个文件名额（每日 5000 份硬上限）。

        成功返回 True（files_used+1）；已满返回 False——调用方应中断解析。
        """
        with self._lock:
            data = self._load()
            if int(data.get("files_used", 0)) >= settings.daily_file_limit:
                return False
            data["files_used"] = int(data.get("files_used", 0)) + 1
            self._save(data)
            return True

    # ── 兼容旧调用（used_today / remaining / add）────────

    def used_today(self) -> int:
        return self.priority_used_today()

    def remaining(self) -> int:
        return self.priority_remaining()

    def add(self, pages: int) -> int:
        return self.add_pages(pages)


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
        返回 {batch_files, batches_total, pages_used, files_reserved, errors, skipped_cached}

        配额语义（2026-08-10 修正）：
        - 优先页数（1000/日）不足**不中断**——MinerU 自动进普通队列排队，只是慢
        - 文件数（5000/日）为硬上限，满额才中断（file_limit_exceeded）
        - 文件数按 PDF 去重：每本 PDF 首次实际调用 API 时占 1 份，
          books.quota_files 持久化，续跑不重复计；全缓存命中则不计
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

        logger.info(
            "parse start book=%s title=%r pages=%d batches=%d batch_size=%d mode=%s",
            book_id, book_title, total_pages, len(batches), batch_size,
            "full" if self.api_key else "flash",
        )

        batch_files: list[str] = []
        errors: list[str] = []
        pages_used = 0
        skipped_cached = 0

        # 该书是否已计入每日文件数（防续跑重复计；全缓存命中则本次不计）
        from ..db import get_conn

        with get_conn() as conn:
            row = conn.execute(
                "SELECT quota_files FROM books WHERE id=?", (book_id,)
            ).fetchone()
        file_reserved = bool(row and row["quota_files"])

        for idx, (start, end) in enumerate(batches, 1):
            batch_file = md_dir / f"batch_{idx:02d}_p{start}-{end}.md"
            if self._batch_complete(batch_file):
                batch_files.append(str(batch_file))
                skipped_cached += 1
                if progress_cb:
                    progress_cb(idx, len(batches))
                continue

            # 文件数硬上限（5000/日）：首次实际调用前原子占位。
            # 优先页数超 1000 不中断——MinerU 自动进普通队列排队，只是慢。
            if not file_reserved:
                if not self.quota.try_reserve_file():
                    msg = f"file_limit_exceeded at batch {idx} (p{start}-{end})"
                    logger.warning("book=%s %s", book_id, msg)
                    errors.append(msg)
                    break
                file_reserved = True
                try:
                    with get_conn() as conn:
                        conn.execute(
                            "UPDATE books SET quota_files=1 WHERE id=?", (book_id,)
                        )
                except Exception:
                    pass

            need = end - start + 1
            pages_str = f"{start}-{end}" if start != end else str(start)
            # B2 有限重试（2026-08-18）：网络类异常重试 2 次（指数退避），
            # 业务失败（云端返回 error）不重试——同页区间重复请求幂等，
            # 但重试只限定连接类错误，避免重复消耗云端额度。
            try:
                out = self._extract(str(pdf_path), pages_str)
            except _RETRYABLE_EXC:
                ok_extract = False
                for delay in RETRY_DELAYS:
                    time.sleep(delay)
                    try:
                        out = self._extract(str(pdf_path), pages_str)
                        ok_extract = True
                        break
                    except _RETRYABLE_EXC:
                        continue
                if not ok_extract:
                    msg = (
                        f"batch {idx} (p{start}-{end}): 网络异常，重试 "
                        f"{len(RETRY_DELAYS)} 次后仍失败"
                    )
                    logger.error("book=%s %s", book_id, msg)
                    errors.append(msg)
                    continue
            except Exception as exc:
                msg = f"batch {idx} (p{start}-{end}): {type(exc).__name__}: {exc}"
                logger.error("book=%s %s", book_id, msg, exc_info=exc)
                errors.append(msg)
                continue

            if out["error"] or not out["markdown"]:
                msg = f"batch {idx} (p{start}-{end}): {out['error'] or 'empty markdown'}"
                logger.error("book=%s %s", book_id, msg)
                errors.append(msg)
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

        if errors:
            logger.warning(
                "parse finished book=%s errors=%d/%d batches, first=%r",
                book_id, len(errors), len(batches), errors[:1],
            )
        else:
            logger.info(
                "parse done book=%s batches=%d pages=%d skipped_cached=%d",
                book_id, len(batches), pages_used, skipped_cached,
            )

        return {
            "batch_files": batch_files,
            "batches_total": len(batches),
            "pages_used": pages_used,
            "files_reserved": 1 if file_reserved else 0,
            "skipped_cached": skipped_cached,
            "errors": errors,
        }
