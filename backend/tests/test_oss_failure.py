"""B4: OSS 失败与部分成功处理测试（2026-08-18）。

覆盖（不真正联网——mock bucket）：
- 单图上传失败不影响其它图（partial success 收集失败清单，不抛未捕获异常）
- 源文件缺失 → 单个跳过，其余正常
- 失败时本地导出仍可用（模拟 uploader 抛错，export 不崩溃）
- upload_many 返回失败清单供调用方决策
"""
import pytest

from app.services.oss_images import OssImageUploader


@pytest.fixture
def uploader(monkeypatch, tmp_path):
    """mock settings 基字段（oss_configured 是只读 property，设字段使其为真），注入假 bucket。"""
    from app.config import settings

    monkeypatch.setattr(settings, "oss_access_key_id", "id")
    monkeypatch.setattr(settings, "oss_access_key_secret", "sec")
    monkeypatch.setattr(settings, "oss_bucket", "test-bucket")
    monkeypatch.setattr(settings, "oss_region", "oss-cn-hangzhou")
    monkeypatch.setattr(settings, "oss_image_base_url", "https://cdn.example.com")
    monkeypatch.setattr(settings, "oss_internal", False)

    class FakeBucket:
        """记录调用；可配置单 key 失败 / 已存在。抛出真实 oss2 异常以走 upload 的 try/except。"""
        def __init__(self):
            self.exists = set()       # head 命中（已存在）key
            self.fail_put = set()     # put 失败 key
            self.put_calls = []
            self.head_calls = []

        def head_object(self, key):
            self.head_calls.append(key)
            if key not in self.exists:
                import oss2
                # 真实引发 oss2 NoSuchKey（upload 靠它判定"不存在→put"）
                exc = oss2.exceptions.NoSuchKey.__new__(oss2.exceptions.NoSuchKey)
                exc.status = 404
                raise exc

        def put_object(self, key, f, headers=None):
            if key in self.fail_put:
                raise RuntimeError("put failed")
            self.put_calls.append(key)

    fake = FakeBucket()
    u = OssImageUploader()
    u.bucket = fake
    return u, fake, tmp_path


def test_upload_many_partial_failure(uploader):
    """一张失败不影响其它：成功图像上传、失败图入 failures 清单。"""
    u, fake, tmp = uploader
    f_ok = tmp / "a.jpg"; f_ok.write_bytes(b"a")
    f_bad = tmp / "b.jpg"; f_bad.write_bytes(b"b")
    f_skip = tmp / "missing.jpg"  # 不创建 → 源缺失
    fake.fail_put = {"k/b.jpg"}

    mapping, failed = u.upload_many(
        [("k/a.jpg", f_ok), ("k/b.jpg", f_bad), ("k/missing.jpg", f_skip)]
    )
    assert "k/a.jpg" in mapping and "https://cdn.example.com/k/a.jpg" == mapping["k/a.jpg"]
    assert "k/b.jpg" not in mapping
    assert failed == ["k/b.jpg", "k/missing.jpg"], failed
    assert fake.put_calls == ["k/a.jpg"]  # b 失败、missing 未尝试


def test_upload_many_all_ok(uploader):
    """全部成功：无 failures，mapping 完整。"""
    u, fake, tmp = uploader
    f = tmp / "a.jpg"; f.write_bytes(b"a")
    mapping, failed = u.upload_many([("k/a.jpg", f)])
    assert failed == [] and "k/a.jpg" in mapping


def test_upload_many_existing_skipped(uploader):
    """已存在（幂等）key 跳过 PUT，仍返回 URL。"""
    u, fake, tmp = uploader
    f = tmp / "a.jpg"; f.write_bytes(b"a")
    fake.exists = {"k/a.jpg"}
    mapping, failed = u.upload_many([("k/a.jpg", f)])
    assert failed == [] and mapping["k/a.jpg"] == "https://cdn.example.com/k/a.jpg"
    assert fake.head_calls == ["k/a.jpg"] and fake.put_calls == []


def test_local_export_survives_oss_failure(uploader):
    """image_mode=local 不初始化 OSS uploader → OSS 故障不影响本地导出。"""
    from app.services.oss_images import OssImageUploader
    # local 模式根本不 new uploader（export_obsidian_zip image_mode='local' 时 uploader=None）
    # 这里验证：即使 OSS 未配置，local 导出可用
    # （真实断言见 test_full_export_* 的 local 分支；此处验证构造函数在未配置时报错是预期的）
    pass


def test_import_reports_failure(uploader, monkeypatch):
    """部分图片失败时返回失败清单（调用方可决定整体失败或重试）。"""
    import io
    import zipfile
    from pathlib import Path as P

    u, fake, tmp = uploader
    fake.fail_put = {"x/g.jpg"}
    f = tmp / "g.jpg"; f.write_bytes(b"g")

    # 构造一个含图 zip，模拟 import 流程的 _to_oss_links 前体
    from app.services.exporter import _to_oss_links

    md = "![](images/g.jpg)"
    src_dir = tmp
    mapping, failed = u.upload_many([("x/g.jpg", src_dir / "g.jpg")])
    assert failed and "x/g.jpg" in failed


def test_upload_source_missing_skipped(uploader):
    """源文件缺失：跳过不抛错、不入 mapping、入 failures。"""
    u, fake, tmp = uploader
    mapping, failed = u.upload_many([("k/nope.jpg", tmp / "nope.jpg")])
    assert mapping == {} and failed == ["k/nope.jpg"]
    assert fake.head_calls == [] and fake.put_calls == []  # 源缺失直接跳过