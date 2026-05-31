#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import shutil
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image

DEFAULT_DATASET_DIR = Path("data/gongbi_v1")
DEFAULT_MAX_PIXELS = 35_000_000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)


def load_config_candidates_per_asset(config_path: Path) -> int:
    if not config_path.exists():
        return 2
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    return int(cfg.get("generation", {}).get("candidates_per_asset", 2))


def remaining_asset_ids(raw_rows: list[dict], candidate_rows: list[dict], candidates_per_asset: int) -> set[str]:
    success_keys = set()
    for row in candidate_rows:
        if row.get("status") == "success":
            try:
                success_keys.add((str(row["asset_id"]), int(row["candidate_index"])))
            except Exception:
                pass

    remaining = set()
    for row in raw_rows:
        asset_id = str(row.get("asset_id", ""))
        if not asset_id:
            continue
        for idx in range(1, candidates_per_asset + 1):
            if (asset_id, idx) not in success_keys:
                remaining.add(asset_id)
                break
    return remaining


def resize_to_max_pixels(src: Path, max_pixels: int) -> tuple[int, int, str]:
    with Image.open(src) as img:
        img.load()
        original_mode = img.mode
        width, height = img.size
        pixels = width * height

        if pixels <= max_pixels:
            return width, height, original_mode

        scale = math.sqrt(max_pixels / pixels)
        new_width = max(1, int(width * scale))
        new_height = max(1, int(height * scale))

        while new_width * new_height > max_pixels:
            if new_width >= new_height:
                new_width -= 1
            else:
                new_height -= 1

        resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        suffix = src.suffix.lower()
        tmp = src.with_name(f"{src.stem}.resize_tmp{src.suffix}")

        if suffix in {".jpg", ".jpeg"}:
            if resized.mode not in {"RGB", "L"}:
                resized = resized.convert("RGB")
            resized.save(tmp, format="JPEG", quality=95, optimize=True)
        elif suffix == ".png":
            resized.save(tmp, format="PNG", optimize=True)
        elif suffix == ".webp":
            resized.save(tmp, format="WEBP", quality=95, method=6)
        else:
            resized.save(tmp)

        tmp.replace(src)

    with Image.open(src) as check:
        check.load()
        return check.width, check.height, check.mode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--config", type=Path, default=Path("configs/pipeline_gongbi_v1.json"))
    parser.add_argument("--max-pixels", type=int, default=DEFAULT_MAX_PIXELS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dataset = args.dataset_dir
    raw_manifest = dataset / "manifests/raw_assets.jsonl"
    candidates_manifest = dataset / "manifests/candidates.jsonl"

    raw_rows = read_jsonl(raw_manifest)
    candidate_rows = read_jsonl(candidates_manifest)
    candidates_per_asset = load_config_candidates_per_asset(args.config)
    remaining = remaining_asset_ids(raw_rows, candidate_rows, candidates_per_asset)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = dataset / "backups" / f"resize_failed_oversize_{ts}"
    manifest_backup = backup_root / "manifests" / "raw_assets.jsonl"

    changed = 0
    skipped_remaining_not_oversize = 0
    skipped_already_complete = 0

    if not args.dry_run:
        manifest_backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(raw_manifest, manifest_backup)

    for row in raw_rows:
        asset_id = str(row.get("asset_id", ""))
        if asset_id not in remaining:
            skipped_already_complete += 1
            continue

        rel = row.get("image_path")
        if not rel:
            continue

        image_path = dataset / str(rel)
        if not image_path.exists():
            print(f"[missing] {asset_id}: {image_path}")
            continue

        with Image.open(image_path) as img:
            img.load()
            old_width, old_height, old_mode = img.width, img.height, img.mode

        old_pixels = old_width * old_height
        if old_pixels <= args.max_pixels:
            skipped_remaining_not_oversize += 1
            continue

        print(f"[resize] {asset_id}: {old_width}x{old_height}={old_pixels} -> <= {args.max_pixels}")

        if args.dry_run:
            changed += 1
            continue

        backup_image = backup_root / "raw_images" / str(rel)
        backup_image.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(image_path, backup_image)

        old_sha = sha256_file(image_path)
        new_width, new_height, new_mode = resize_to_max_pixels(image_path, args.max_pixels)
        new_sha = sha256_file(image_path)

        row["original_width_before_seed_resize"] = old_width
        row["original_height_before_seed_resize"] = old_height
        row["original_mode_before_seed_resize"] = old_mode
        row["original_sha256_before_seed_resize"] = old_sha
        row["backup_path_before_seed_resize"] = backup_image.relative_to(dataset).as_posix()
        row["resized_for_seed_api"] = True
        row["resize_max_pixels"] = args.max_pixels
        row["resized_at"] = utc_now()
        row["width"] = new_width
        row["height"] = new_height
        row["mode"] = new_mode
        row["sha256"] = new_sha

        changed += 1
        print(f"[ok] {asset_id}: {new_width}x{new_height}={new_width * new_height}")

    if not args.dry_run:
        write_jsonl(raw_manifest, raw_rows)

    print()
    print("== resize failed oversize raw assets ==")
    print("dataset:", dataset)
    print("candidates_per_asset:", candidates_per_asset)
    print("remaining asset ids:", len(remaining))
    print("changed:", changed)
    print("skipped already complete:", skipped_already_complete)
    print("skipped remaining but not oversize:", skipped_remaining_not_oversize)
    if args.dry_run:
        print("dry_run: true")
    else:
        print("backup:", backup_root)
        print("manifest updated:", raw_manifest)


if __name__ == "__main__":
    main()
