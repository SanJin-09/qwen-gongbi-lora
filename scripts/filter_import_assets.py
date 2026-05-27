from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

THRESHOLDS = {
    "person": (768, 512),      # min_long_edge, min_short_edge
    "landscape": (1024, 768),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--import-dir", type=Path, default=Path("data/gongbi_v1/import"))
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--max-megapixels", type=float, default=60.0)
    parser.add_argument("--check-duplicates", action="store_true")
    parser.add_argument("--move-rejected", action="store_true")
    parser.add_argument("--delete", action="store_true")
    parser.add_argument("--yes", action="store_true")
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unique_target(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 1
    while True:
        candidate = parent / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def inspect_image(path: Path, category: str, check_duplicates: bool, seen_hashes: dict[str, str], max_mp: float) -> dict[str, Any]:
    row: dict[str, Any] = {
        "category": category,
        "path": path.as_posix(),
        "ok": False,
        "reason": None,
        "width": None,
        "height": None,
        "mode": None,
        "sha256": None,
        "duplicate_of": None,
    }

    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        row["reason"] = "unsupported_extension"
        return row

    try:
        with Image.open(path) as image:
            width, height = image.size
            mode = image.mode
            pixels = width * height
            row.update({"width": width, "height": height, "mode": mode})

            if max_mp > 0 and pixels > max_mp * 1_000_000:
                row["reason"] = f"too_large_over_{max_mp:g}mp"
                return row

            image.verify()
    except Exception as exc:
        row["reason"] = "open_error"
        row["error"] = repr(exc)
        return row

    min_long, min_short = THRESHOLDS.get(category, (1024, 768))
    long_edge = max(int(row["width"]), int(row["height"]))
    short_edge = min(int(row["width"]), int(row["height"]))
    if long_edge < min_long or short_edge < min_short:
        row["reason"] = f"too_small_need_long_{min_long}_short_{min_short}"
        return row

    if check_duplicates:
        try:
            digest = file_sha256(path)
            row["sha256"] = digest
        except Exception as exc:
            row["reason"] = "hash_error"
            row["error"] = repr(exc)
            return row

        if digest in seen_hashes:
            row["reason"] = "duplicate"
            row["duplicate_of"] = seen_hashes[digest]
            return row
        seen_hashes[digest] = path.as_posix()

    row["ok"] = True
    row["reason"] = "pass"
    return row


def main() -> None:
    args = parse_args()

    if args.move_rejected and args.delete:
        raise SystemExit("--move-rejected 和 --delete 不能同时使用")
    if (args.move_rejected or args.delete) and not args.yes:
        raise SystemExit("要移除文件必须显式加 --yes")

    if not args.import_dir.exists():
        raise SystemExit(f"import dir not found: {args.import_dir}")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = args.report or Path("data/gongbi_v1/manifests") / f"import_quality_report_{run_id}.jsonl"
    rejected_root = Path("data/gongbi_v1/import_rejected") / run_id

    rows: list[dict[str, Any]] = []
    seen_hashes: dict[str, str] = {}

    for category_dir in sorted(p for p in args.import_dir.iterdir() if p.is_dir()):
        category = category_dir.name
        for path in sorted(category_dir.rglob("*")):
            if not path.is_file():
                continue
            rows.append(inspect_image(path, category, args.check_duplicates, seen_hashes, args.max_megapixels))

    summary = Counter()
    by_category = Counter()
    rejected = [row for row in rows if not row["ok"]]

    for row in rows:
        summary["total"] += 1
        summary["pass" if row["ok"] else "reject"] += 1
        by_category[(row["category"], "pass" if row["ok"] else "reject")] += 1
        by_category[(row["category"], row["reason"])] += 1

    actions = Counter()
    for row in rejected:
        path = Path(row["path"])
        if args.move_rejected:
            target = unique_target(rejected_root / row["category"] / path.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(path, target)
            row["action"] = "moved"
            row["target"] = target.as_posix()
            actions["moved"] += 1
        elif args.delete:
            path.unlink()
            row["action"] = "deleted"
            actions["deleted"] += 1
        else:
            row["action"] = "dry_run"

    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    print("== Import image quality report ==")
    print(f"import_dir: {args.import_dir}")
    print(f"report: {report}")
    print(f"total: {summary['total']}")
    print(f"pass: {summary['pass']}")
    print(f"reject: {summary['reject']}")

    print("\n== By category ==")
    categories = sorted({row["category"] for row in rows})
    for category in categories:
        print(f"{category}: pass={by_category[(category, 'pass')]}, reject={by_category[(category, 'reject')]}")

    print("\n== Reject reasons ==")
    for category in categories:
        reasons = sorted(
            reason for (cat, reason), count in by_category.items()
            if cat == category and reason not in {"pass", "reject"} and count
        )
        for reason in reasons:
            print(f"{category}: {reason} = {by_category[(category, reason)]}")

    if actions:
        print("\n== Actions ==")
        for action, count in actions.items():
            print(f"{action}: {count}")

    print("\n== First rejected examples ==")
    for row in rejected[:30]:
        print(f"{row['category']} | {row.get('width')}x{row.get('height')} | {row['reason']} | {row['path']}")


if __name__ == "__main__":
    main()
    