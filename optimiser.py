#!/usr/bin/env python3
"""
Website Image Optimiser + Template Updater + Optional Cleanup

Changes:
- Convert ALL raster images to WebP.
- Resize only if larger than target using ImageMagick ">" modifier.
- No resolution-based skipping.

Other features:
- Input root with img/, templates/, master/
- [giant] -> 1920px else 1200px
- Strip EXIF, preserve transparency, optional lossless for alpha
- Skips animated GIFs
- Parallel processing
- Case-insensitive, word-bounded replacements in templates
- Atomic writes for templates
- conversion_map.txt and template_updates.log
- --remove-originals deletes .png/.jpg/.jpeg/.gif in img/ after success

Requires: Python 3.8+, ImageMagick, Pillow
"""

import argparse
import concurrent.futures as cf
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple, Dict, List

try:
    from PIL import Image
except ImportError:
    print("Pillow is required. Install with: pip install pillow", file=sys.stderr)
    sys.exit(1)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
RASTER_EXTS = {".png", ".jpg", ".jpeg", ".gif"}
ORIGINALS_DIRNAME = "Originals"
CONV_MAP_FILENAME = "conversion_map.txt"
TEMPLATE_LOG_FILENAME = "template_updates.log"

FNAME_CHARS = r"A-Za-z0-9._\-"

def find_imagemagick_bin(explicit: Optional[str] = None) -> Tuple[str, bool]:
    candidates = []
    if explicit:
        candidates.append(explicit)
    candidates += ["convert", "magick"]
    for exe in candidates:
        try:
            out = subprocess.run([exe, "-version"], capture_output=True, text=True)
            if out.returncode == 0 and ("ImageMagick" in out.stdout or "ImageMagick" in out.stderr):
                requires_wrapper = (exe == "magick")
                return exe, requires_wrapper
        except FileNotFoundError:
            continue
    print("Could not find ImageMagick. Install it or pass --imagemagick-bin", file=sys.stderr)
    sys.exit(1)

def is_animated_gif(path: Path) -> bool:
    if path.suffix.lower() != ".gif":
        return False
    try:
        with Image.open(path) as im:
            return getattr(im, "is_animated", False) and im.n_frames > 1
    except Exception:
        return False

def get_image_info(path: Path) -> Tuple[int, int, bool, str]:
    with Image.open(path) as im:
        w, h = im.size
        mode = im.mode
        fmt = (im.format or "").upper()
        has_alpha = ("A" in mode) or (im.info.get("transparency") is not None)
        return w, h, has_alpha, fmt

def backup_original(src: Path, originals_dir: Path) -> None:
    originals_dir.mkdir(exist_ok=True)
    base = src.stem
    for p in originals_dir.iterdir():
        if p.is_file() and p.stem == base:
            return
    shutil.copy2(src, originals_dir / src.name)

def needs_processing(src: Path, dst_webp: Path, overwrite: bool) -> bool:
    if overwrite or not dst_webp.exists():
        return True
    return src.stat().st_mtime > dst_webp.stat().st_mtime

def build_convert_cmd(
    im_bin: str,
    requires_wrapper: bool,
    src: Path,
    dst: Path,
    target_width: int,
    quality: int,
    use_lossless_for_alpha: bool,
    has_alpha: bool,
    extra_webp_args: Optional[str],
) -> list:
    cmd = []
    if requires_wrapper:
        cmd += [im_bin, "convert"]
    else:
        cmd += [im_bin]
    # ">" means only shrink, never enlarge
    cmd += [str(src), "-resize", f"{target_width}x>", "-strip"]
    if has_alpha and use_lossless_for_alpha:
        cmd += ["-define", "webp:lossless=true"]
    else:
        cmd += ["-quality", str(quality), "-define", "webp:method=6"]
    if extra_webp_args:
        cmd += extra_webp_args.split()
    cmd += [str(dst)]
    return cmd

def process_one(
    src: Path,
    out_dir: Path,
    originals_dir: Path,
    im_bin: str,
    requires_wrapper: bool,
    max_width: int,
    max_width_giant: int,
    quality: int,
    use_lossless_for_alpha: bool,
    overwrite: bool,
    dry_run: bool,
    remove_originals: bool,
    deletion_log: List[str],
) -> Tuple[str, Optional[Tuple[str, str]]]:
    try:
        if not src.is_file() or src.suffix.lower() not in IMAGE_EXTS:
            return f"SKIP  Not an image: {src.name}", None
        if is_animated_gif(src):
            return f"SKIP  Animated GIF not processed: {src.name}", None

        width, height, has_alpha, _ = get_image_info(src)
        is_giant = "[giant]" in src.name.lower()
        target_width = max_width_giant if is_giant else max_width

        backup_original(src, originals_dir)

        dst_name = f"{src.stem}.webp"
        dst_path = out_dir / dst_name

        # If up to date, we may still remove the raster if requested
        if not needs_processing(src, dst_path, overwrite):
            if remove_originals and src.suffix.lower() in RASTER_EXTS:
                if dry_run:
                    print(f"DRY   REMOVE {src.name}")
                else:
                    try:
                        src.unlink()
                        deletion_log.append(f"Removed original raster: {src.name}")
                    except Exception as e:
                        deletion_log.append(f"Failed to remove {src.name}: {e}")
            return f"SKIP  Up to date: {dst_name}", (src.name, dst_name)

        cmd = build_convert_cmd(
            im_bin=im_bin,
            requires_wrapper=requires_wrapper,
            src=src,
            dst=dst_path,
            target_width=target_width,
            quality=quality,
            use_lossless_for_alpha=use_lossless_for_alpha,
            has_alpha=has_alpha,
            extra_webp_args=None,
        )

        if dry_run:
            msg = "DRY   " + " ".join(cmd)
            if remove_originals and src.suffix.lower() in RASTER_EXTS:
                msg += f"  && REMOVE {src.name}"
            return msg, (src.name, dst_name)

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return f"ERR   {src.name}: {proc.stderr.strip() or proc.stdout.strip()}", None

        if remove_originals and src.suffix.lower() in RASTER_EXTS:
            try:
                src.unlink()
                deletion_log.append(f"Removed original raster: {src.name}")
            except Exception as e:
                deletion_log.append(f"Failed to remove {src.name}: {e}")

        return f"DONE  {src.name} -> {dst_name}  [{width}x{height} -> ≤{target_width}w, {'alpha' if has_alpha else 'opaque'}]", (src.name, dst_name)

    except Exception as e:
        return f"ERR   {src.name}: {e}", None

def collect_images(img_dir: Path, recursive: bool) -> List[Path]:
    if recursive:
        return [p for p in img_dir.rglob("*") if p.suffix.lower() in IMAGE_EXTS and ORIGINALS_DIRNAME not in p.parts]
    return [p for p in img_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]

def write_text_atomic(target: Path, text: str) -> None:
    tmp = target.with_suffix(target.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, target)

def ensure_backup(src_file: Path, backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    dst = backup_dir / src_file.name
    if not dst.exists():
        shutil.copy2(src_file, dst)

def build_safe_pattern(filename: str) -> re.Pattern:
    escaped = re.escape(filename)
    pattern = rf"(?<![{FNAME_CHARS}]){escaped}(?![{FNAME_CHARS}])"
    return re.compile(pattern, flags=re.IGNORECASE)

def update_templates(root: Path, mapping: Dict[str, str], log_file: Path, dry_run: bool) -> None:
    templates_dir = root / "templates"
    master_dir = root / "master"
    targets = []
    for base in [templates_dir, master_dir]:
        if base.exists():
            targets += [p for p in base.rglob("*") if p.suffix.lower() in {".html", ".md"}]
    if not targets:
        return

    patterns = {old: build_safe_pattern(old) for old in mapping}

    with open(log_file, "a", encoding="utf-8") as log:
        for file_path in targets:
            backup_dir = file_path.parent / "Backup"
            try:
                text = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = file_path.read_text(encoding="latin-1")

            original_text = text
            applied = []

            for old, new in mapping.items():
                pat = patterns[old]
                new_text, count = pat.subn(new, text)
                if count > 0:
                    text = new_text
                    applied.append((old, new, count))

            if applied and text != original_text:
                if not dry_run:
                    ensure_backup(file_path, backup_dir)
                    write_text_atomic(file_path, text)
                for old, new, count in applied:
                    log.write(f"{file_path.relative_to(root)} :: {old} -> {new} ({count} repl)\n")
                action = "DRY  " if dry_run else "EDIT "
                print(f"{action}{file_path.relative_to(root)}  replacements: {len(applied)}")
            else:
                print(f"SKIP {file_path.relative_to(root)}  no matches")

def main():
    parser = argparse.ArgumentParser(description="Optimise images in img/ and update references in templates/ and master/.")
    parser.add_argument("--root", default=".", help="Project root containing img/, templates/, master/")
    parser.add_argument("--recursive", action="store_true", help="Recurse into img/ subfolders")
    parser.add_argument("--max-width", type=int, default=1200, help="Max width for normal images")
    parser.add_argument("--max-width-giant", type=int, default=1920, help="Max width when filename contains [giant]")
    parser.add_argument("--quality", type=int, default=80, help="WebP quality for lossy output")
    parser.add_argument("--lossless-alpha", action="store_true", help="Use lossless WebP if image has alpha")
    parser.add_argument("--threads", type=int, default=os.cpu_count() or 4, help="Worker threads")
    parser.add_argument("--overwrite", action="store_true", help="Recreate WebP even if up to date")
    parser.add_argument("--dry-run", action="store_true", help="Show planned actions only")
    parser.add_argument("--remove-originals", action="store_true", help="Remove .png/.jpg/.jpeg/.gif in img/ after successful WebP creation and backup")
    parser.add_argument("--imagemagick-bin", default=None, help='ImageMagick binary. For example "convert" or "magick"')
    args = parser.parse_args()

    root = Path(args.root).resolve()
    img_dir = root / "img"
    templates_dir = root / "templates"
    master_dir = root / "master"

    if not img_dir.exists():
        print(f"img/ not found under root: {root}", file=sys.stderr)
        sys.exit(1)

    originals_dir = img_dir / ORIGINALS_DIRNAME
    conv_map_path = img_dir / CONV_MAP_FILENAME
    template_log_path = img_dir / TEMPLATE_LOG_FILENAME

    im_bin, requires_wrapper = find_imagemagick_bin(args.imagemagick_bin)

    images = collect_images(img_dir, args.recursive)
    if not images:
        print("No images found in img/. Proceeding to template update in case only references need changes.")

    print(f"Found {len(images)} image(s) in {img_dir}")
    print(f"Backups: {originals_dir}")
    print(f"Widths: normal={args.max_width}px, giant={args.max_width_giant}px, quality={args.quality}, "
          f"lossless alpha={'on' if args.lossless_alpha else 'off'}")
    print(f"Threads={args.threads}, overwrite={'on' if args.overwrite else 'off'}, dry-run={'on' if args.dry_run else 'off'}, remove originals={'on' if args.remove_originals else 'off'}")

    mapping_pairs: List[Tuple[str, str]] = []
    deletion_log: List[str] = []

    work = []
    for p in images:
        work.append((
            p, img_dir, originals_dir, im_bin, requires_wrapper,
            args.max_width, args.max_width_giant, args.quality,
            args.lossless_alpha, args.overwrite, args.dry_run,
            args.remove_originals, deletion_log
        ))

    with cf.ThreadPoolExecutor(max_workers=args.threads) as ex:
        futures = [ex.submit(process_one, *w) for w in work]
        for fut in cf.as_completed(futures):
            status, pair = fut.result()
            print(status)
            if pair:
                mapping_pairs.append(pair)

    mapping: Dict[str, str] = {}
    for old_name, new_name in mapping_pairs:
        mapping[old_name] = new_name

    # Also map any existing non-webp that already have a webp sibling
    for p in images:
        if p.suffix.lower() != ".webp":
            candidate = img_dir / f"{p.stem}.webp"
            if candidate.exists():
                mapping.setdefault(p.name, candidate.name)

    if not args.dry_run and mapping:
        with open(conv_map_path, "w", encoding="utf-8") as f:
            for old, new in sorted(mapping.items()):
                f.write(f"{old} -> {new}\n")
        print(f"Wrote conversion map: {conv_map_path}")

    if not args.dry_run and deletion_log:
        with open(template_log_path, "a", encoding="utf-8") as log:
            for line in deletion_log:
                log.write(f"{line}\n")

    if mapping and (templates_dir.exists() or master_dir.exists()):
        update_templates(root=root, mapping=mapping, log_file=template_log_path, dry_run=args.dry_run)
        if not args.dry_run:
            print(f"Template update log: {template_log_path}")
    else:
        print("No template updates performed. Either no mapping or templates/master not found.")

if __name__ == "__main__":
    main()

