"""应用配置：从环境变量 / .env 读取。"""
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 数据目录（空/未设置时用默认：项目根/data）
    data_dir: Path | None = None

    @field_validator("data_dir", mode="before")
    @classmethod
    def _data_dir_default(cls, v):
        if not v:
            return BASE_DIR.parent / "data"
        return v

    # MinerU 云 API
    mineru_api_key: str = ""
    mineru_base_url: str = ""

    # Obsidian vault（可空：配置后「导入 Obsidian」按钮生效）
    obsidian_vault_dir: Path | None = None
    obsidian_sub_dir: str = "教材"  # vault 内教材存放子目录

    @field_validator("obsidian_vault_dir", mode="before")
    @classmethod
    def _vault_dir_default(cls, v):
        if not v:
            return None
        return Path(v)

    # OSS 图片外链（可空：配置后导出/导入支持「图片转 OSS」模式）
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_bucket: str = ""
    oss_region: str = "oss-cn-hangzhou"
    # 图片公网 URL 前缀（空则自动拼 https://<bucket>.<region>.aliyuncs.com/；配 CDN 后改此值）
    oss_image_base_url: str = ""
    # 服务器部署（与桶同地域）时走内网 endpoint，免公网下行流量费
    oss_internal: bool = False

    @property
    def oss_configured(self) -> bool:
        return bool(self.oss_access_key_id and self.oss_access_key_secret)

    @property
    def oss_endpoint(self) -> str:
        if self.oss_internal:
            return f"https://{self.oss_region}-internal.aliyuncs.com"
        return f"https://{self.oss_region}.aliyuncs.com"

    @property
    def oss_image_base(self) -> str:
        if self.oss_image_base_url:
            return self.oss_image_base_url.rstrip("/")
        return f"https://{self.oss_bucket}.{self.oss_region}.aliyuncs.com"

    # 解析分批大小（页）
    parse_batch_size: int = 25
    # MinerU 每日配额（页）
    daily_quota_pages: int = 1000

    @property
    def db_path(self) -> Path:
        return self.data_dir / "kb.db"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def md_dir(self) -> Path:
        return self.data_dir / "md"

    @property
    def build_dir(self) -> Path:
        return self.data_dir / "build"

    @property
    def vectors_dir(self) -> Path:
        return self.data_dir / "vectors"

    @property
    def quota_file(self) -> Path:
        return self.data_dir / "quota.json"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.raw_dir, self.md_dir, self.build_dir, self.vectors_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
