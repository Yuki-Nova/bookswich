"""OSS 图片上传服务：导出/导入时把 images/ 本地图传到 OSS_BUCKET 桶。

md 里的图片引用（`images/xxx.jpg`）替换为 OSS 公网 URL（`<base>/<书名>/images/xxx.jpg`），
vault 只留文本，图片存 OSS —— 为多端同步（WebDAV/Syncthing）缩小 vault 体积。

幂等：图片名是 MinerU 的 hash，key 恒定；head_object 命中即跳过，重复导出不重复上传。
"""
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

import oss2

from ..config import settings

logger = logging.getLogger(__name__)


class OssImageUploader:
    """幂等上传器（同一 key 已存在则跳过）。"""

    # 按扩展名给出正确 MIME（MinerU 输出主要是 jpg，偶有 png/webp）
    _CONTENT_TYPES = {
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".svg": "image/svg+xml",
        ".jpeg": "image/jpeg",
        ".jpg": "image/jpeg",
    }

    def __init__(self) -> None:
        if not settings.oss_configured:
            raise RuntimeError(
                "未配置 OSS（backend/.env 缺少 OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET）"
            )
        self.bucket = oss2.Bucket(
            oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret),
            settings.oss_endpoint,
            settings.oss_bucket,
        )

    def _content_type(self, local_path: Path) -> str:
        return self._CONTENT_TYPES.get(local_path.suffix.lower(), "image/jpeg")

    def upload(self, key: str, local_path: Path) -> str:
        """上传单张图片（幂等），返回公网 URL。"""
        ct = self._content_type(local_path)
        try:
            self.bucket.head_object(key)
            logger.info("OSS 已存在，跳过: %s", key)
        except oss2.exceptions.NoSuchKey:
            with open(local_path, "rb") as f:
                self.bucket.put_object(key, f, headers={"Content-Type": ct})
            logger.info("OSS 上传: %s", key)
        # key 中不可见字符/签名参数等其它 404 形态（NoSuchKey 是 NotFound 子类，
        # 这里再兜一层防止 SDK 版本差异抛 NotFound）
        except oss2.exceptions.NotFound:
            with open(local_path, "rb") as f:
                self.bucket.put_object(key, f, headers={"Content-Type": ct})
            logger.info("OSS 上传(404 兜底): %s", key)
        return settings.oss_image_base + "/" + quote(key, safe="/")

    def upload_many(self, items: list[tuple[str, Path]]) -> tuple[dict[str, str], list[str]]:
        """批量上传，返回 (mapping, failed)。顺序上传（单次导出图片量 ~100-500，足够）。

        B4（2026-08-18）：部分成功处理——
        - 单图失败仅计入 failed，不影响其它图继续上传（不再整体中断）
        - 源文件缺失：直接跳过（入 failed，不尝试 head/put）
        - 已存在（幂等）返回 URL 不计入 failed
        调用方据 failed 决定整体失败 / 重试 / 部分接受的提示。
        """
        mapping: dict[str, str] = {}
        failed: list[str] = []
        for key, src in items:
            if not src.exists():
                failed.append(key)
                continue
            try:
                mapping[key] = self.upload(key, src)
            except Exception as exc:  # noqa: BLE001 — 网络/权限/异构异常统一进失败清单
                logger.warning("OSS 上传失败 key=%s: %s", key, exc)
                failed.append(key)
        return mapping, failed

    def delete_prefix(self, prefix: str) -> int:
        """删除指定 key 前缀下的全部对象（best-effort），返回删除数。

        用于删除教材时清理孤儿图片（key 规则 <书名>/images/…）。失败抛异常，
        由调用方决定是否吞掉（删除教材主流程不应被 OSS 故障阻塞）。
        """
        keys: list[str] = []
        for obj in oss2.ObjectIterator(self.bucket, prefix=prefix, max_keys=1000):
            keys.append(obj.key)
        if not keys:
            return 0
        for i in range(0, len(keys), 1000):
            self.bucket.batch_delete_objects(keys[i : i + 1000])
        logger.info("OSS 删除 %d 个对象: %s*", len(keys), prefix)
        return len(keys)
