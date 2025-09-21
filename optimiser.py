#!/usr/bin/env python3
"""
Website Image Optimiser + Responsive Variants + Template Updater + Optional Cleanup
+ Dimensions CSV + HTML width/height injection + lazy loading

Changes vs previous:
- Generates multiple responsive widths per image (e.g. 360, 720, 1200).
- Keeps {stem}.webp as the largest variant for backwards compatibility.
- Updates HTML <img> tags to add:
    * srcset with discovered variants
    * sizes (configurable; sensible default)
    * loading="lazy" (unless opted-out)
    * decoding="async"
- Preserves/updates width and height attributes when known.
- Optional per-filename sizes mapping via JSON (e.g. img/sizes.json).

Requires: Python 3.8+, ImageMagick, Pillow
"""

import argparse
import concurrent.futures as cf
import csv
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple, Dict, List, Sequence

try:
    from PIL import Image
except ImportError:
    print("Pillow is required. Install with: pip install pillow", file=sys.stderr)
    sys.exit(1)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}  # SVG intentionally excluded
RASTER_EXTS = {".png", ".jpg", ".jpeg", ".gif"}
ORIGINALS_DIRNAME = "Originals"
CONV_MAP_FILENAME = "conversion_map.txt"
TEMPLATE_LOG_FILENAME = "template_updates.log"
SIZES_JSON = "sizes.json"  # optional config in img/

FNAME_CHARS = r"A-Za-z0-9._\-"

# Regex to find <img ... src="..."> case-insensitively
IMG_TAG_RE = re.compile(r"<img\b[^>]*\bsrc\s*=\s*(['\"])(?P<src>[^'\"]+)\1[^>]*>", re.IGNORECASE)
WIDTH_RE = re.compile(r"\bwidth\s*=\s*(['\"])[^'\"]+\1", re.IGNORECASE)
HEIGHT_RE = re.compile(r"\bheight\s*=\s*(['\"])[^'\"]+\1", re.IGNORECASE)
LOADING_RE = re.compile(r"\bloading\s*=\s*(['\"])[^'\"]+\1", re.IGNORECASE)
DECODING_RE = re.compile(r"\bdecoding\s*=\s*(['\"])[^'\"]+\1", re.IGNORECASE)
SRCSET_RE = re.compile(r"\bsrcset\s*=\s*(['\"]).*?\1", re.IGNORECASE | re.DOTALL)
SIZES_ATTR_RE = re.compile(r"\bsizes\s*=\s*(['\"]).*?\1", re.IGNORECASE | re.DOTALL)

# Transient and editor artefacts to ignore
TRANSIENT_SUFFIXES = {".swp", ".tmp", ".bak"}
def is_transient(p: Path) -> bool:
    n = p.name
    return (
        n.startswith(".#")         # Emacs lockfiles
        or n.endswith("~")         # backup files
        or n == ".DS_Store"
        or p.suffix.lower() in TRANSIENT_SUFFIXES
    )

def parse_variant_widths(s: str) -> List[int]:
    try:
        widths = sorted({int(x.strip()) for x in s.split(",") if x.strip()})
        return [w for w in widths if w > 0]
    except Exception:
        raise argparse.ArgumentTypeError("Invalid --variant-widths. Example: 360,720,1200")

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

def needs_processing(src: Path, dst: Path, overwrite: bool) -> bool:
    if overwrite or not dst.exists():
        return True
    return src.stat().st_mtime > dst.stat().st_mtime

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
    # ">" shrinks only
    cmd += [str(src), "-resize", f"{target_width}x>", "-strip"]
    if has_alpha and use_lossless_for_alpha:
        cmd += ["-define", "webp:lossless=true"]
    else:
        cmd += ["-quality", str(quality), "-define", "webp:method=6"]
    if extra_webp_args:
        cmd += extra_webp_args.split()
    cmd += [str(dst)]
    return cmd

def ensure_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)

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

# ---------- Identify size ----------

def identify_size_with_im(im_bin: str, requires_wrapper: bool, path: Path) -> Optional[Tuple[int, int]]:
    try:
        if requires_wrapper:
            cmd = [im_bin, "identify", "-format", "%w %h", str(path)]
        else:
            base = "identify" if im_bin == "convert" else im_bin
            cmd = [base, "-format", "%w %h", str(path)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            parts = proc.stdout.strip().split()
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return None

def read_size(path: Path, im_bin: str, requires_wrapper: bool) -> Optional[Tuple[int, int]]:
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return identify_size_with_im(im_bin, requires_wrapper, path)

# ---------- CSV helpers ----------

def write_dimensions_csv(img_dir: Path, images: List[Path], out_csv: Path, im_bin: str, requires_wrapper: bool) -> int:
    rows = []
    for p in images:
        try:
            size = read_size(p, im_bin, requires_wrapper)
            if size:
                w, h = size
                fmt = ""
                try:
                    with Image.open(p) as im:
                        fmt = im.format or ""
                except Exception:
                    fmt = ""
                rows.append({
                    "relative_path": str(p.relative_to(img_dir)),
                    "filename": p.name,
                    "width": w,
                    "height": h,
                    "format": fmt,
                    "animated_gif": "yes" if (p.suffix.lower() == ".gif" and is_animated_gif(p)) else "no",
                })
            else:
                rows.append({
                    "relative_path": str(p.relative_to(img_dir)),
                    "filename": p.name,
                    "width": "",
                    "height": "",
                    "format": "",
                    "animated_gif": "",
                    "error": "could not read size",
                })
        except Exception as e:
            rows.append({
                "relative_path": str(p.relative_to(img_dir)),
                "filename": p.name,
                "width": "",
                "height": "",
                "format": "",
                "animated_gif": "",
                "error": str(e),
            })
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["relative_path", "filename", "width", "height", "format", "animated_gif", "error"]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            if "error" not in r:
                r["error"] = ""
            writer.writerow(r)
    return len(rows)

def build_dims_maps(img_dir: Path, images: List[Path], im_bin: str, requires_wrapper: bool) -> Tuple[Dict[str, Tuple[int,int]], Dict[str, Tuple[int,int]]]:
    by_basename: Dict[str, Tuple[int,int]] = {}
    by_relpath: Dict[str, Tuple[int,int]] = {}
    for p in images:
        size = read_size(p, im_bin, requires_wrapper)
        if not size:
            continue
        w, h = size
        rel = p.relative_to(img_dir).as_posix()
        by_basename[p.name] = (w, h)
        by_relpath[f"img/{rel}"] = (w, h)  # site paths start with img/
    return by_basename, by_relpath

# ---------- Variant generation ----------

def variant_name(stem: str, width: int) -> str:
    return f"{stem}-{width}.webp"

def generate_variants_for(
    src: Path,
    out_dir: Path,
    im_bin: str,
    requires_wrapper: bool,
    variant_widths: Sequence[int],
    quality: int,
    use_lossless_for_alpha: bool,
    overwrite: bool,
) -> Tuple[List[Tuple[int, Path]], Optional[Path], str]:
    """
    Returns ([(w, path), ...], path_to_max_as_base, status_msg)
    Also ensures {stem}.webp equals the largest variant (re-rendered if needed).
    """
    width, height, has_alpha, _ = get_image_info(src)
    stem = src.stem
    created: List[Tuple[int, Path]] = []
    max_w = max(variant_widths) if variant_widths else width

    # Produce each width
    for w in sorted(set(variant_widths)):
        dst = out_dir / variant_name(stem, w)
        if needs_processing(src, dst, overwrite):
            cmd = build_convert_cmd(im_bin, requires_wrapper, src, dst, w, quality, use_lossless_for_alpha, has_alpha, None)
            ensure_dir(dst)
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                return created, None, f"ERR   {src.name} [{width}x{height}] variant {w}: {proc.stderr.strip() or proc.stdout.strip()}"
        created.append((w, dst))

    # Ensure {stem}.webp as largest variant
    largest_dst = out_dir / f"{stem}.webp"
    if needs_processing(src, largest_dst, overwrite):
        cmd = build_convert_cmd(im_bin, requires_wrapper, src, largest_dst, max_w, quality, use_lossless_for_alpha, has_alpha, None)
        ensure_dir(largest_dst)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return created, None, f"ERR   {src.name} base {max_w}: {proc.stderr.strip() or proc.stdout.strip()}"

    # Reflect base in created list if not already same width
    if max_w not in [w for w, _ in created]:
        created.append((max_w, largest_dst))

    return created, largest_dst, f"DONE  {src.name} -> {[f'{w}w' for w, _ in sorted(created)]} (max={max_w})"

# ---------- HTML updates (srcset/sizes/lazy/decoding + width/height) ----------

def load_sizes_map(json_path: Path) -> List[Tuple[str, str]]:
    """
    Returns list of (pattern, sizes_value) pairs. Patterns are glob-style and match the basename.
    Example JSON (img/sizes.json):
      {
        "front_*": "(max-width: 768px) 90vw, 356px",
        "logo_*": "120px"
      }
    """
    if not json_path.exists():
        return []
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        items = []
        for pattern, sizes in data.items():
            if isinstance(pattern, str) and isinstance(sizes, str) and pattern and sizes:
                items.append((pattern, sizes))
        return items
    except Exception:
        return []

def find_sizes_for(basename: str, sizes_map: List[Tuple[str, str]], default_sizes: str) -> str:
    for pattern, sizes in sizes_map:
        if fnmatch.fnmatch(basename, pattern):
            return sizes
    return default_sizes

def build_srcset_candidates(img_dir: Path, basename: str) -> List[Tuple[int, str]]:
    """
    Look for img/{stem}-{w}.webp and include {stem}.webp as the largest candidate.
    Returns list of (width, url_path) sorted ascending.
    """
    stem, _ = os.path.splitext(basename)
    # Collect -{w}.webp variants
    candidates: List[Tuple[int, str]] = []
    for p in (img_dir).glob(f"{stem}-*.webp"):
        # parse "-{w}.webp"
        m = re.search(r"-(\d+)\.webp$", p.name)
        if m:
            w = int(m.group(1))
            candidates.append((w, f"img/{p.name}"))
    # Add {stem}.webp if exists and not duplicate
    base = img_dir / f"{stem}.webp"
    if base.exists():
        # Try to infer width from file name list; if unknown, use a large sentinel so it sorts last
        known_ws = [w for w, _ in candidates]
        base_w = max(known_ws) if known_ws else 99999
        candidates.append((base_w, f"img/{base.name}"))
    # De-dup and sort
    dedup: Dict[str, int] = {}
    for w, url in candidates:
        dedup[url] = w
    out = sorted([(w, url) for url, w in dedup.items()], key=lambda x: x[0])
    return out

def insert_or_replace_attr(tag: str, attr: str, value: str) -> str:
    patt = re.compile(rf"\b{attr}\s*=\s*(['\"]).*?\1", re.IGNORECASE | re.DOTALL)
    if patt.search(tag):
        return patt.sub(f'{attr}="{value}"', tag)
    # insert before '>'
    end = tag.rfind(">")
    if end == -1:
        return tag
    i = end - 1
    while i >= 0 and tag[i].isspace():
        i -= 1
    if i >= 0 and tag[i] == "/":
        return tag[:i] + f' {attr}="{value}"' + tag[i:]
    return tag[:end] + f' {attr}="{value}"' + tag[end:]

def inject_img_attributes(
    root: Path,
    img_dir: Path,
    dims_by_base: Dict[str, Tuple[int,int]],
    dims_by_rel: Dict[str, Tuple[int,int]],
    sizes_map: List[Tuple[str, str]],
    default_sizes: str,
    force_lazy: bool,
    log_file: Path,
    dry_run: bool
) -> None:
    targets = []
    for folder in ["templates", "master"]:
        d = root / folder
        if d.exists():
            targets += [p for p in d.rglob("*.html") if not is_transient(p)]

    if not targets:
        return

    with open(log_file, "a", encoding="utf-8") as log:
        for file_path in targets:
            try:
                try:
                    text = file_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    text = file_path.read_text(encoding="latin-1")
            except FileNotFoundError:
                print(f"SKIP {file_path.relative_to(root)}  vanished during scan")
                continue
            except Exception as e:
                print(f"SKIP {file_path.relative_to(root)}  read error: {e}")
                continue

            original = text
            edits = 0
            replacements = []

            def repl(m: re.Match) -> str:
                nonlocal edits
                tag = m.group(0)
                src = m.group("src").strip()

                # Only local paths inside img/ and not SVG or data URLs
                if not (src.startswith("img/") or src.startswith("/img/")):
                    return tag
                if src.lower().endswith(".svg") or src.lower().startswith("data:"):
                    return tag

                # normalise to "img/..."
                key_rel = src[1:] if src.startswith("/") else src
                basename = Path(key_rel).name

                # Dimensions (prefer exact relpath, then basename)
                dims = dims_by_rel.get(key_rel) or dims_by_base.get(basename)
                if dims:
                    w, h = dims
                    if not WIDTH_RE.search(tag):
                        tag = insert_or_replace_attr(tag, "width", str(w))
                    if not HEIGHT_RE.search(tag):
                        tag = insert_or_replace_attr(tag, "height", str(h))

                # Build srcset candidates based on files present
                candidates = build_srcset_candidates(img_dir, basename)
                if candidates:
                    srcset_str = ", ".join([f"{url} {width}w" for width, url in candidates])
                    tag = insert_or_replace_attr(tag, "srcset", srcset_str)

                    # sizes: from map, else default
                    sizes_val = find_sizes_for(basename, sizes_map, default_sizes)
                    tag = insert_or_replace_attr(tag, "sizes", sizes_val)

                    # Set src to the smallest reasonable candidate as a fallback
                    smallest_url = candidates[0][1]
                    tag = insert_or_replace_attr(tag, "src", smallest_url)

                # loading="lazy" and decoding="async"
                # Skip forcing lazy if explicit data-lcp, fetchpriority="high" or loading already present
                tag_lower = tag.lower()
                is_priority = ("data-lcp" in tag_lower) or ('fetchpriority="high"' in tag_lower)
                if force_lazy and not is_priority and not LOADING_RE.search(tag):
                    tag = insert_or_replace_attr(tag, "loading", "lazy")
                if not DECODING_RE.search(tag):
                    tag = insert_or_replace_attr(tag, "decoding", "async")

                edits += 1
                replacements.append((basename, "updated"))
                return tag

            text = IMG_TAG_RE.sub(repl, text)

            if edits and text != original:
                backup_dir = file_path.parent / "Backup"
                if not dry_run:
                    ensure_backup(file_path, backup_dir)
                    write_text_atomic(file_path, text)
                for base, _ in replacements:
                    log.write(f"{file_path.relative_to(root)} :: responsive attrs for {base}\n")
                print(f"{'DRY  ' if dry_run else 'EDIT '}{file_path.relative_to(root)}  responsive updates: {edits}")
            else:
                print(f"SKIP {file_path.relative_to(root)}  no responsive changes")

# ---------- Template filename replacements (legacy) ----------

def update_templates_filenames(root: Path, mapping: Dict[str, str], log_file: Path, dry_run: bool) -> None:
    # Retained for completeness. With srcset we do not need to rewrite names,
    # but we keep it to migrate any stale references if desired.
    templates_dir = root / "templates"
    master_dir = root / "master"
    targets = []
    for base in [templates_dir, master_dir]:
        if base.exists():
            targets += [
                p for p in base.rglob("*")
                if p.suffix.lower() in {".html", ".md"} and not is_transient(p)
            ]
    if not targets:
        return

    patterns = {old: build_safe_pattern(old) for old in mapping}

    with open(log_file, "a", encoding="utf-8") as log:
        for file_path in targets:
            try:
                try:
                    text = file_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    text = file_path.read_text(encoding="latin-1")
            except FileNotFoundError:
                print(f"SKIP {file_path.relative_to(root)}  vanished during scan")
                continue
            except Exception as e:
                print(f"SKIP {file_path.relative_to(root)}  read error: {e}")
                continue

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
                    ensure_backup(file_path, file_path.parent / "Backup")
                    write_text_atomic(file_path, text)
                for old, new, count in applied:
                    log.write(f"{file_path.relative_to(root)} :: {old} -> {new} ({count} repl)\n")
                action = "DRY  " if dry_run else "EDIT "
                print(f"{action}{file_path.relative_to(root)}  replacements: {len(applied)}")
            else:
                print(f"SKIP {file_path.relative_to(root)}  no filename matches")

# ---------- Main processing ----------

def process_one(
    src: Path,
    out_dir: Path,
    originals_dir: Path,
    im_bin: str,
    requires_wrapper: bool,
    variant_widths: Sequence[int],
    quality: int,
    use_lossless_for_alpha: bool,
    overwrite: bool,
    dry_run: bool,
    remove_originals: bool,
    deletion_log: List[str],
) -> Tuple[str, Optional[List[Tuple[str, str]]]]:
    """
    Returns status string and optional [(old_name, new_name), ...] mappings for legacy replacement.
    """
    try:
        if not src.is_file() or src.suffix.lower() not in IMAGE_EXTS:
            return f"SKIP  Not an image: {src.name}", None
        if is_animated_gif(src):
            return f"SKIP  Animated GIF not processed: {src.name}", None

        backup_original(src, originals_dir)

        # Generate variants if raster or already webp
        if src.suffix.lower() in (RASTER_EXTS | {".webp"}):
            if dry_run:
                msg = f"DRY   variants {[w for w in variant_widths]} for {src.name}"
                # Simulate mapping: keep {stem}.webp as base
                base_name = f"{src.stem}.webp"
                pairs = [(src.name, base_name)] if src.suffix.lower() != ".webp" else []
                return msg, pairs

            variants, base_path, status = generate_variants_for(
                src=src,
                out_dir=out_dir,
                im_bin=im_bin,
                requires_wrapper=requires_wrapper,
                variant_widths=variant_widths,
                quality=quality,
                use_lossless_for_alpha=use_lossless_for_alpha,
                overwrite=overwrite
            )
            if base_path is None:
                return status, None

            # Optionally remove original rasters once variants exist
            if remove_originals and src.suffix.lower() in RASTER_EXTS:
                try:
                    src.unlink()
                    deletion_log.append(f"Removed original raster: {src.name}")
                except Exception as e:
                    deletion_log.append(f"Failed to remove {src.name}: {e}")

            # Legacy mapping: point old raster name to base {stem}.webp
            pairs: List[Tuple[str, str]] = []
            if src.suffix.lower() != ".webp":
                pairs.append((src.name, base_path.name))

            return status, pairs

        return f"SKIP  Unsupported: {src.name}", None

    except Exception as e:
        return f"ERR   {src.name}: {e}", None

def main():
    parser = argparse.ArgumentParser(description="Optimise images in img/ with responsive variants and update HTML.")
    parser.add_argument("--root", default=".", help="Project root containing img/, templates/, master/")
    parser.add_argument("--recursive", action="store_true", help="Recurse into img/ subfolders")
    parser.add_argument("--variant-widths", type=parse_variant_widths, default="360,720,1200",
                        help="Comma-separated widths to generate (e.g. 360,720,1200)")
    parser.add_argument("--quality", type=int, default=80, help="WebP quality for lossy output")
    parser.add_argument("--lossless-alpha", action="store_true", help="Use lossless WebP if image has alpha")
    parser.add_argument("--threads", type=int, default=os.cpu_count() or 4, help="Worker threads")
    parser.add_argument("--overwrite", action="store_true", help="Recreate WebP even if up to date")
    parser.add_argument("--dry-run", action="store_true", help="Show planned actions only")
    parser.add_argument("--remove-originals", action="store_true", help="Remove .png/.jpg/.jpeg/.gif in img/ after successful WebP creation and backup")
    parser.add_argument("--imagemagick-bin", default=None, help='ImageMagick binary. For example "convert" or "magick"')

    # Dimensions CSV options
    parser.add_argument("--no-dimensions", action="store_true", help="Do not write the dimensions CSV")
    parser.add_argument("--dimensions-out", default=None, help="Path to write dimensions CSV (default: img/image_dimensions.csv)")

    # HTML control
    parser.add_argument("--default-sizes", default="(max-width: 768px) 90vw, 356px",
                        help='Default "sizes" attribute to use when no pattern matches (e.g. "(max-width: 768px) 90vw, 356px")')
    parser.add_argument("--no-html-update", action="store_true", help="Skip HTML updates (srcset/sizes/lazy/width/height)")
    parser.add_argument("--no-lazy", action="store_true", help="Do not add loading=lazy (leave existing tags unchanged)")

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
    dims_csv_path = Path(args.dimensions_out) if args.dimensions_out else (img_dir / "image_dimensions.csv")

    im_bin, requires_wrapper = find_imagemagick_bin(args.imagemagick_bin)

    images = collect_images(img_dir, args.recursive)
    if not images:
        print("No images found in img/. Proceeding to template update in case only references need changes.")
    else:
        if not args.no_dimensions:
            count = write_dimensions_csv(img_dir, images, dims_csv_path, im_bin, requires_wrapper)
            print(f"Wrote {count} entries to {dims_csv_path}")

    print(f"Found {len(images)} image(s) in {img_dir}")
    print(f"Backups: {originals_dir}")
    print(f"Variants: {args.variant_widths} px, quality={args.quality}, lossless alpha={'on' if args.lossless_alpha else 'off'}")
    print(f"Threads={args.threads}, overwrite={'on' if args.overwrite else 'off'}, dry-run={'on' if args.dry_run else 'off'}, remove originals={'on' if args.remove_originals else 'off'}")

    mapping_pairs: List[Tuple[str, str]] = []
    deletion_log: List[str] = []

    # Convert in parallel (generate variants)
    work = []
    for p in images:
        # Only process actual rasters or existing webp files
        if p.suffix.lower() in IMAGE_EXTS:
            work.append((
                p, img_dir, originals_dir, im_bin, requires_wrapper,
                args.variant_widths, args.quality, args.lossless_alpha,
                args.overwrite, args.dry_run, args.remove_originals, deletion_log
            ))

    with cf.ThreadPoolExecutor(max_workers=args.threads) as ex:
        futures = [ex.submit(process_one, *w) for w in work]
        for fut in cf.as_completed(futures):
            status, pairs = fut.result()
            print(status)
            if pairs:
                mapping_pairs.extend(pairs)

    # Build mapping old -> new (legacy raster name -> base .webp)
    mapping: Dict[str, str] = {}
    for old_name, new_name in mapping_pairs:
        mapping[old_name] = new_name

    # Write conversion map
    if not args.dry_run and mapping:
        with open(conv_map_path, "w", encoding="utf-8") as f:
            for old, new in sorted(mapping.items()):
                f.write(f"{old} -> {new}\n")
        print(f"Wrote conversion map: {conv_map_path}")

    # Update legacy filename references if needed (not strictly required with srcset)
    if mapping and (templates_dir.exists() or master_dir.exists()):
        update_templates_filenames(root=root, mapping=mapping, log_file=template_log_path, dry_run=args.dry_run)

    # Build dims maps from current files including variants
    if not args.no_html_update:
        all_imgs_now = collect_images(img_dir, args.recursive)
        dims_by_base, dims_by_rel = build_dims_maps(img_dir, all_imgs_now, im_bin, requires_wrapper)

        # Load optional sizes map
        sizes_map = load_sizes_map(img_dir / SIZES_JSON)

        # Inject attributes into HTML
        inject_img_attributes(
            root=root,
            img_dir=img_dir,
            dims_by_base=dims_by_base,
            dims_by_rel=dims_by_rel,
            sizes_map=sizes_map,
            default_sizes=args.default_sizes,
            force_lazy=(not args.no_lazy),
            log_file=template_log_path,
            dry_run=args.dry_run
        )
        if not args.dry_run:
            print(f"Template update log: {template_log_path}")
    else:
        print("HTML responsive updates skipped (--no-html-update).")

    # Append deletion log
    if not args.dry_run and deletion_log:
        with open(template_log_path, "a", encoding="utf-8") as log:
            for line in deletion_log:
                log.write(f"{line}\n")

if __name__ == "__main__":
    main()
