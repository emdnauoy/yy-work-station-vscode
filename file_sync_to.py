# -*- coding: utf-8 -*-
"""
文件同步脚本 — 配置文件驱动，支持复制/移动/同步
用法：python file_sync.py                    # 执行所有 enabled 任务
      python file_sync.py --list             # 列出所有任务
      python file_sync.py --run "任务名"      # 执行指定任务
      python file_sync.py --dry-run          # 预览模式，不
      实际操作
      python file_sync.py --src X --dst Y    # 直接指定路径（覆盖配置）
"""

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "file_sync_config.json"


def format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f}GB"


def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        print(f"[ERROR] 配置文件不存在: {config_path}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def match_pattern(filename: str, pattern: str) -> bool:
    if pattern == "*":
        return True
    return fnmatch.fnmatch(filename.lower(), pattern.lower())


def is_excluded(file_path: Path, src_path: Path, exclude_folders: list,
                exclude_files: list) -> bool:
    """检查文件是否在排除列表中"""
    try:
        rel = file_path.relative_to(src_path)
    except ValueError:
        return False
    parts = rel.parts
    for folder in exclude_folders:
        if folder in parts:
            return True
    for pat in exclude_files:
        if fnmatch.fnmatch(file_path.name.lower(), pat.lower()):
            return True
    return False


def is_included(file_path: Path, src_path: Path, include_folders: list,
                include_files: list) -> bool:
    """检查文件是否在包含列表中。列表为空 = 不过滤（全部包含）"""
    if not include_folders and not include_files:
        return True  # 未设置 include = 全部通过
    try:
        rel = file_path.relative_to(src_path)
    except ValueError:
        return False
    parts = rel.parts
    # 包含文件夹：路径中任意一段匹配
    for folder in include_folders:
        if folder in parts:
            return True
    # 包含文件：文件名匹配
    for pat in include_files:
        if fnmatch.fnmatch(file_path.name.lower(), pat.lower()):
            return True
    return False


def collect_files(src: str, pattern: str, recursive: bool,
                  exclude_folders: list = None, exclude_files: list = None,
                  include_folders: list = None, include_files: list = None) -> list:
    src_path = Path(src)
    if not src_path.exists():
        print(f"[WARN] 源目录不存在: {src}")
        return []
    exclude_folders = exclude_folders or []
    exclude_files = exclude_files or []
    include_folders = include_folders or []
    include_files = include_files or []
    files = []
    iterator = src_path.rglob("*") if recursive else src_path.glob("*")
    for f in iterator:
        if not f.is_file():
            continue
        if not match_pattern(f.name, pattern):
            continue
        if not is_included(f, src_path, include_folders, include_files):
            continue
        if is_excluded(f, src_path, exclude_folders, exclude_files):
            continue
        files.append(f)
    return sorted(files)


def file_hash(file_path: str) -> str:
    """计算文件 MD5"""
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def is_file_changed(src_file: Path, dst_file: Path) -> bool:
    """比较源文件和目标文件是否有变化（mtime + size，快速模式）"""
    if not dst_file.exists():
        return True  # 目标不存在，需要复制
    src_stat = src_file.stat()
    dst_stat = dst_file.stat()
    # mtime 差超过 1 秒或 size 不同，认为有变化
    if abs(src_stat.st_mtime - dst_stat.st_mtime) > 1:
        return True
    if src_stat.st_size != dst_stat.st_size:
        return True
    return False


def is_file_changed_hash(src_file: Path, dst_file: Path) -> bool:
    """比较源文件和目标文件是否有变化（MD5，精确模式）"""
    if not dst_file.exists():
        return True
    return file_hash(str(src_file)) != file_hash(str(dst_file))


def run_task(task: dict, dry_run: bool = False, changed_only: bool = False,
             check_hash: bool = False) -> dict:
    name = task.get("name", "未命名")
    op = task.get("operation", "copy")
    src = task.get("src", "")
    dst = task.get("dst", "")
    pattern = task.get("pattern", "*")
    recursive = task.get("recursive", False)
    exclude_folders = task.get("exclude_folders", [])
    exclude_files = task.get("exclude_files", [])
    include_folders = task.get("include_folders", [])
    include_files = task.get("include_files", [])

    if not src or not dst:
        return {"name": name, "status": "skip", "reason": "src 或 dst 为空"}

    src_path = Path(src)
    dst_path = Path(dst)

    if not src_path.exists():
        return {"name": name, "status": "error", "reason": f"源目录不存在: {src}"}

    dst_path.mkdir(parents=True, exist_ok=True)

    files = collect_files(src, pattern, recursive, exclude_folders, exclude_files,
                          include_folders, include_files)
    if not files:
        return {"name": name, "status": "ok", "copied": 0, "reason": "无匹配文件"}

    total = len(files)
    total_size = sum(f.stat().st_size for f in files)
    copied = 0
    skipped = 0
    copied_size = 0
    errors = []
    width = len(str(total))
    compare_fn = is_file_changed_hash if check_hash else is_file_changed

    for f in files:
        try:
            rel = f.relative_to(src_path)
            target = dst_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            fsize = f.stat().st_size
            size_str = format_size(fsize)

            # 变动检测：跳过未变更文件
            if changed_only and not compare_fn(f, target):
                skipped += 1
                continue

            pct = (copied / total * 100) if total else 0
            progress = f"  [{copied + 1:>{width}}/{total} {pct:5.1f}%]"

            if dry_run:
                print(f"{progress} [DRY] {op}: {rel} ({size_str})")
                copied += 1
                copied_size += fsize
                continue

            if op == "copy":
                shutil.copy2(str(f), str(target))
            elif op == "move":
                shutil.move(str(f), str(target))
            else:
                errors.append(f"未知操作: {op}")
                continue
            copied += 1
            copied_size += fsize
            print(f"{progress} {op}: {rel} ({size_str})")
        except Exception as e:
            errors.append(f"{f.name}: {e}")

    return {
        "name": name,
        "status": "ok" if not errors else "partial",
        "operation": op,
        "total": total,
        "copied": copied,
        "skipped": skipped,
        "total_size": format_size(total_size),
        "copied_size": format_size(copied_size),
        "errors": errors,
    }


def run_all(config: dict, dry_run: bool = False, changed_only: bool = False,
            check_hash: bool = False):
    tasks = config.get("tasks", [])
    enabled = [t for t in tasks if t.get("enabled", True)]
    if not enabled:
        print("[INFO] 没有启用的任务")
        return

    print(f"[INFO] 执行 {len(enabled)} 个任务...")
    for task in enabled:
        print(f"\n--- {task.get('name', '未命名')} ---")
        result = run_task(task, dry_run, changed_only, check_hash)
        status = result.get("status", "unknown")
        if status == "ok":
            op = result.get("operation", "copy")
            total = result.get("total", 0)
            copied = result.get("copied", 0)
            skipped = result.get("skipped", 0)
            size = result.get("copied_size", "0B")
            skip_str = f"，跳过 {skipped} 个" if skipped else ""
            print(f"  [{status.upper()}] {op} {copied}/{total} 个文件 ({size}){skip_str}")
        elif status == "partial":
            size = result.get("copied_size", "0B")
            print(f"  [PARTIAL] {result.get('copied', 0)}/{result.get('total', 0)} 成功 ({size})")
            for err in result.get("errors", []):
                print(f"    ERROR: {err}")
        else:
            print(f"  [{status.upper()}] {result.get('reason', '')}")


def run_by_name(config: dict, task_name: str, dry_run: bool = False,
                changed_only: bool = False, check_hash: bool = False):
    tasks = config.get("tasks", [])
    matched = [t for t in tasks if t.get("name") == task_name]
    if not matched:
        print(f"[ERROR] 未找到任务: {task_name}")
        print("可用任务:")
        for t in tasks:
            print(f"  - {t.get('name', '未命名')}")
        return
    for task in matched:
        print(f"\n--- {task.get('name')} ---")
        result = run_task(task, dry_run, changed_only, check_hash)
        print(f"  结果: {json.dumps(result, ensure_ascii=False, indent=2)}")


def direct_run(src: str, dst: str, pattern: str = "*", recursive: bool = False,
               operation: str = "copy", dry_run: bool = False,
               exclude_folders: list = None, exclude_files: list = None,
               include_folders: list = None, include_files: list = None,
               changed_only: bool = False, check_hash: bool = False):
    task = {
        "name": "直接执行",
        "operation": operation,
        "src": src,
        "dst": dst,
        "pattern": pattern,
        "recursive": recursive,
        "exclude_folders": exclude_folders or [],
        "exclude_files": exclude_files or [],
        "include_folders": include_folders or [],
        "include_files": include_files or [],
    }
    result = run_task(task, dry_run, changed_only, check_hash)
    print(f"结果: {json.dumps(result, ensure_ascii=False, indent=2)}")


def list_tasks(config: dict):
    tasks = config.get("tasks", [])
    if not tasks:
        print("[INFO] 配置文件中没有任务")
        return
    print(f"共 {len(tasks)} 个任务:\n")
    for i, t in enumerate(tasks, 1):
        enabled = "ON" if t.get("enabled", True) else "OFF"
        name = t.get("name", "未命名")
        op = t.get("operation", "copy")
        src = t.get("src", "")
        dst = t.get("dst", "")
        pattern = t.get("pattern", "*")
        rec = "递归" if t.get("recursive") else "仅当前"
        print(f"  {i}. [{enabled}] {name}")
        print(f"     {op} | {pattern} | {rec}")
        print(f"     {src}")
        print(f"     → {dst}")
        print()


def main():
    parser = argparse.ArgumentParser(description="文件同步脚本")
    parser.add_argument("--config", type=str, default=str(CONFIG_FILE), help="配置文件路径")
    parser.add_argument("--list", action="store_true", help="列出所有任务")
    parser.add_argument("--run", type=str, help="执行指定名称的任务")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际操作")
    parser.add_argument("--src", type=str, help="源目录（直接模式）")
    parser.add_argument("--dst", type=str, help="目标目录（直接模式）")
    parser.add_argument("--pattern", type=str, default="*", help="文件匹配模式，如 *.pdf")
    parser.add_argument("--recursive", action="store_true", help="递归子目录")
    parser.add_argument("--exclude-folder", action="append", default=[],
                        help="排除文件夹名，可多次使用（如 --exclude-folder node_modules --exclude-folder .git）")
    parser.add_argument("--exclude-file", action="append", default=[],
                        help="排除文件名/模式，可多次使用（如 --exclude-file *.pyc --exclude-file .DS_Store）")
    parser.add_argument("--include-folder", action="append", default=[],
                        help="只传输指定文件夹，可多次使用（设置后只传匹配的）")
    parser.add_argument("--include-file", action="append", default=[],
                        help="只传输指定文件名/模式，可多次使用（设置后只传匹配的）")
    parser.add_argument("--operation", type=str, default="copy", choices=["copy", "move"],
                        help="操作类型：copy 或 move")
    parser.add_argument("--no-changed-only", action="store_true",
                        help="禁用变动检测，强制复制所有文件")
    parser.add_argument("--no-check-hash", action="store_true",
                        help="禁用 MD5 检测，改用 mtime + size（更快但不精确）")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)
    # run_name = args.run
    run_name = "distribution_order_reverse"
    pattern = args.pattern
    recursive = args.recursive
    operation = args.operation
    exclude_folders = args.exclude_folder
    exclude_files = args.exclude_file
    include_folders = args.include_folder
    include_files = args.include_file
    dry_run = args.dry_run
    changed_only = not args.no_changed_only
    check_hash = not args.no_check_hash
    src = args.src
    dst = args.dst

    if args.list:
        list_tasks(config)
    elif run_name:
        run_by_name(config, run_name, dry_run, changed_only, check_hash)
    elif args.src and args.dst:
        direct_run(src, dst, pattern, recursive, operation,
                   dry_run, exclude_folders, exclude_files,
                   include_folders, include_files, changed_only, check_hash)
    else:
        run_all(config, dry_run, changed_only, check_hash)


if __name__ == "__main__":
    main()
