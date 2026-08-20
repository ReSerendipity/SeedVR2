"""webui_enhancement.py 文件列表管理核心逻辑测试。"""

from app.integrated_app.optimization.webui_enhancement import (
    FileItem,
    FileItemStatus,
    FileListManager,
    FileListProgress,
)


def test_file_item_to_dict():
    item = FileItem(path="/a/b.png", name="b.png")
    d = item.to_dict()
    assert d["name"] == "b.png"
    assert d["status"] == "pending"
    assert d["elapsed_seconds"] == 0.0
    assert item.elapsed_seconds == 0.0  # start_time=0


def test_file_item_elapsed_with_end():
    item = FileItem(path="/a", name="a", start_time=100.0, end_time=150.0)
    assert item.elapsed_seconds == 50.0


def test_file_list_progress():
    p = FileListProgress(total=10, done=4, failed=1, skipped=1)
    assert p.overall_progress == 0.6
    assert p.is_complete is False
    p2 = FileListProgress(total=0)
    assert p2.overall_progress == 0.0
    p3 = FileListProgress(total=3, done=3)
    assert p3.is_complete is True
    d = p.to_dict()
    assert d["total"] == 10


def test_manager_add_and_progress(tmp_path):
    m = FileListManager()
    f = tmp_path / "x.png"
    f.write_bytes(b"\x00" * 2048)
    item = m.add_file(str(f))
    assert item.name == "x.png"
    assert item.file_size_mb > 0.0

    # 重复添加返回同一对象
    assert m.add_file(str(f)) is item

    # 批量添加
    items = m.add_files([str(tmp_path / "a.png"), str(tmp_path / "b.png")])
    assert len(items) == 2


def test_manager_update_progress_and_remove(tmp_path):
    m = FileListManager()
    f = tmp_path / "y.png"
    f.write_bytes(b"1")
    m.add_file(str(f))

    # 更新进度 -> PENDING -> PROCESSING
    assert m.update_progress(str(f), progress=0.5, step="restore") is True
    item = m._files[str(f)]
    assert item.status == FileItemStatus.PROCESSING
    assert item.progress == 0.5
    assert item.current_step == "restore"

    # 处理中不可移除
    assert m.remove_file(str(f)) is False

    # 标记完成
    assert m.mark_done(str(f), output_path="/out/result.png") is True
    assert item.status == FileItemStatus.DONE
    assert item.output_path == "/out/result.png"
    assert m.remove_file(str(f)) is True

    # 不存在的文件
    assert m.update_progress("/nope.png") is False
    assert m.remove_file("/nope.png") is False


def test_manager_mark_failed(tmp_path):
    m = FileListManager()
    f = tmp_path / "z.png"
    f.write_bytes(b"1")
    m.add_file(str(f))
    assert m.mark_failed(str(f), error_message="boom") is True
    item = m._files[str(f)]
    assert item.status == FileItemStatus.FAILED
    assert item.error_message == "boom"
