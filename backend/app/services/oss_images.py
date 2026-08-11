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

    def upload(self, key: str, local_path: Path) -> str:
        """上传单张图片（幂等），返回公网 URL。"""
        try:
            self.bucket.head_object(key)
            logger.info("OSS 已存在，跳过: %s", key)
        except oss2.exceptions.NoSuchKey:
            with open(local_path, "rb") as f:
                self.bucket.put_object(key, f, headers={"Content-Type": "image/jpeg"})
            logger.info("OSS 上传: %s", key)
        # key 中不可见字符/签名参数等其它 404 形态（NoSuchKey 是 NotFound 子类，
        # 这里再兜一层防止 SDK 版本差异抛 NotFound）
        except oss2.exceptions.NotFound:
            with open(local_path, "rb") as f:
                self.bucket.put_object(key, f, headers={"Content-Type": "image/jpeg"})
            logger.info("OSS 上传(404 兜底): %s", key)
        return settings.oss_image_base + "/" + quote(key, safe="/")

    def upload_many(self, items: list[tuple[str, Path]]) -> dict[str, str]:
        """批量上传，返回 {key: 公网 URL} 映射。顺序上传（单次导出图片量 ~100-500，足够）。"""
        mapping: dict[str, str] = {}
        for key, src in items:
            mapping[key] = self.upload(key, src)
        return mapping

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
