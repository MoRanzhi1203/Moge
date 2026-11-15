##############################
# core/resources/cli.py - 资源获取命令行
##############################

import argparse
import json
import sys
from pathlib import Path

from Moge.core.resources.manager import ResourceManager


def _manager(args) -> ResourceManager:
    return ResourceManager(Path(args.root) if args.root else None)


def command_list(args):
    with _manager(args) as manager:
        if args.edition == "bedrock":
            rows = manager.list_bedrock_versions()
        else:
            rows = manager.list_java_versions(release_only=not args.include_snapshots, limit=args.limit)
        for row in rows:
            print(
                f"{row['edition']:8} {row['version']:18} {row.get('version_type',''):10} "
                f"{row['status']:14} blocks={row.get('blocks', 0)}"
            )
    return 0


def command_fetch(args):
    with _manager(args) as manager:
        if args.edition == "bedrock":
            result = manager.fetch_bedrock(
                args.version,
                force=args.force,
                dry_run=args.dry_run,
                progress=lambda percent, text: print(f"[{percent:3d}%] {text}", file=sys.stderr),
                should_cancel=lambda: False,
            )
        else:
            result = manager.fetch_java(
                args.version,
                force=args.force,
                dry_run=args.dry_run,
                progress=lambda percent, text: print(f"[{percent:3d}%] {text}", file=sys.stderr),
                should_cancel=lambda: False,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_range(args):
    with _manager(args) as manager:
        versions = manager.resolve_java_range(args.start, args.end, release_only=not args.include_snapshots)
        if args.dry_run:
            print(json.dumps(versions, ensure_ascii=False, indent=2))
            return 0
        failures = []
        for version in versions:
            try:
                manager.fetch_java(version, force=args.force)
                print(f"OK {version}")
            except Exception as exc:
                failures.append((version, str(exc)))
                print(f"FAIL {version}: {exc}", file=sys.stderr)
        if failures:
            print(json.dumps({"failures": failures}, ensure_ascii=False, indent=2))
            return 1
    return 0


def command_sync(args):
    with _manager(args) as manager:
        print(json.dumps(manager.sync_java_manifest(force=args.force), ensure_ascii=False, indent=2))
        rows = manager.list_bedrock_versions()
        print(f"bedrock releases: {len(rows)} targets")
    return 0


def command_verify(args):
    with _manager(args) as manager:
        result = manager.verify(args.edition, args.version, full=args.full)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1


def command_delete(args):
    with _manager(args) as manager:
        print(json.dumps(manager.delete(args.edition, args.version), ensure_ascii=False, indent=2))
    return 0


def command_rebuild(args):
    with _manager(args) as manager:
        print(json.dumps(manager.rebuild(args.edition, args.version), ensure_ascii=False, indent=2))
    return 0


def command_report(args):
    with _manager(args) as manager:
        report = manager.report()
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(payload, encoding="utf-8")
            print(f"报告已写入 {args.output}")
        else:
            print(payload)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="moge-resources", description="Moge Minecraft 资源获取")
    parser.add_argument("--root", help="资源根目录（默认 %%LOCALAPPDATA%%\\Moge\\resources）")
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="列出可用版本")
    listing.add_argument("--edition", choices=("java", "bedrock"), default="java")
    listing.add_argument("--limit", type=int, default=0)
    listing.add_argument("--include-snapshots", action="store_true")
    listing.set_defaults(func=command_list)

    fetch = sub.add_parser("fetch", help="获取单个版本")
    fetch.add_argument("--edition", choices=("java", "bedrock"), default="java")
    fetch.add_argument("--version", required=True)
    fetch.add_argument("--force", action="store_true")
    fetch.add_argument("--dry-run", action="store_true")
    fetch.set_defaults(func=command_fetch)

    fetch_range = sub.add_parser("fetch-range", help="获取 Java 版本范围")
    fetch_range.add_argument("--start", required=True)
    fetch_range.add_argument("--end", required=True)
    fetch_range.add_argument("--force", action="store_true")
    fetch_range.add_argument("--dry-run", action="store_true")
    fetch_range.add_argument("--include-snapshots", action="store_true")
    fetch_range.set_defaults(func=command_range)

    sync = sub.add_parser("sync-manifest", help="同步官方版本元数据")
    sync.add_argument("--force", action="store_true")
    sync.set_defaults(func=command_sync)

    verify = sub.add_parser("verify", help="校验已有缓存")
    verify.add_argument("--edition", choices=("java", "bedrock"), default="java")
    verify.add_argument("--version", required=True)
    verify.add_argument("--full", action="store_true")
    verify.set_defaults(func=command_verify)

    delete = sub.add_parser("delete", help="删除版本缓存")
    delete.add_argument("--edition", choices=("java", "bedrock"), default="java")
    delete.add_argument("--version", required=True)
    delete.set_defaults(func=command_delete)

    rebuild = sub.add_parser("rebuild", help="从缓存资源重建索引")
    rebuild.add_argument("--edition", choices=("java", "bedrock"), default="java")
    rebuild.add_argument("--version", required=True)
    rebuild.set_defaults(func=command_rebuild)

    report = sub.add_parser("report", help="输出版本覆盖报告")
    report.add_argument("--output")
    report.set_defaults(func=command_report)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
