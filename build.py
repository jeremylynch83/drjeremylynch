import os
import re
import glob
import subprocess
import unicodedata
import string
import html
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Any

# Optional environment override for base URL
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://www.drjeremylynch.com/")

SPECIAL_SECTIONS = {"features", "news"}

# =======================
# Utilities
# =======================

def _ensure_base_url(url: str) -> str:
    """Normalise base URL to https://.../ form."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if not url.endswith("/"):
        url += "/"
    return url

BASE_URL = _ensure_base_url(SITE_BASE_URL)

def abs_url(path: str) -> str:
    """Return absolute URL for path or passthrough if already absolute."""
    if not path:
        return ""
    if path.startswith(("http://", "https://")):
        return path
    return BASE_URL + path.lstrip("/")

def slugify(text: str) -> str:
    """Make a safe filename slug from text."""
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
    valid = f"-_.{string.ascii_letters}{string.digits}"
    text = ''.join(ch if ch in valid or ch == ' ' else '_' for ch in text)
    text = '_'.join(text.split())
    return text.strip('_') or "section"

def yaml_quote(s: str) -> str:
    """Quote a string safely for simple YAML metadata usage."""
    return '"' + s.replace('"', '\\"') + '"'

def display_section_name(section: str) -> str:
    """Pretty display name for a section label."""
    if section.lower() == "features":
        return "Features"
    if section.lower() == "news":
        return "News"
    return section

def parse_tags_field(tags_value: str) -> List[str]:
    """Parse a comma separated list of tags into a clean list preserving order."""
    if not tags_value:
        return []
    parts = [t.strip() for t in tags_value.split(',')]
    seen = set()
    out: List[str] = []
    for p in parts:
        if not p:
            continue
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out

def norm_tag(tag: str) -> str:
    return unicodedata.normalize('NFKC', tag).strip().lower()

def create_sitemap(base_url: str) -> None:
    """
    Create sitemap.xml for all generated .html files in the current directory.
    Uses file modification time for <lastmod>.
    """
    base_url = _ensure_base_url(base_url)

    html_files = [f for f in glob.glob("*.html")]

    # Put index first, All_topics second, then the rest alphabetically
    ordered: List[str] = []
    for special in ("index.html", "All_topics.html"):
        if special in html_files:
            ordered.append(special)
            html_files.remove(special)
    ordered += sorted(html_files, key=lambda s: s.lower())

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]

    for fn in ordered:
        mtime = datetime.fromtimestamp(os.path.getmtime(fn), tz=timezone.utc)
        lastmod = mtime.isoformat(timespec='seconds').replace('+00:00', 'Z')
        priority = "1.0" if fn == "index.html" else ("0.8" if fn == "All_topics.html" else "0.5")
        lines += [
            "  <url>",
            f"    <loc>{base_url}{fn}</loc>",
            f"    <lastmod>{lastmod}</lastmod>",
            f"    <priority>{priority}</priority>",
            "  </url>"
        ]

    lines.append("</urlset>")

    with open("sitemap.xml", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("Created sitemap.xml")

# =======================
# Parsing and grouping
# =======================

def parse_headings_and_group(file_path: str):
    """
    Parse H1 headings with '{SectionName}' to build:
      - grouped_headings: { section_label: [(url, text), ...] }  (excludes features/news)
      - page_to_section:  { "SectionSlug_TitleSlug.html": section_label }
      - group_names:      { section_label: display_name }
      - section_first:    { section_label: first page link or listing page for specials }
    """
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        lines = f.read().splitlines()

    grouped_headings: Dict[str, List[Tuple[str, str]]] = {}
    page_to_section: Dict[str, str] = {}
    group_names: Dict[str, str] = {}
    section_first: Dict[str, str] = {}

    heading_pattern = re.compile(r'^(#+)\s+(.*?)\s*\{(.+?)\}\s*$')

    for raw in lines:
        m = heading_pattern.match(raw.strip())
        if not m:
            continue
        level, text, section = m.groups()
        if level != '#':
            continue

        section = section.strip()
        sec_lower = section.lower()
        link = f"{slugify(section)}_{slugify(text)}.html"

        page_to_section[link] = section
        group_names.setdefault(section, display_section_name(section))

        if sec_lower not in SPECIAL_SECTIONS:
            grouped_headings.setdefault(section, []).append((link, text))

        if section not in section_first:
            if sec_lower == "features":
                section_first[section] = "Features.html"
            elif sec_lower == "news":
                section_first[section] = "News.html"
            else:
                section_first[section] = link

    return grouped_headings, page_to_section, group_names, section_first


class PageInfo:
    __slots__ = (
        'filename', 'title', 'section', 'sec_lower', 'tags', 'tags_norm',
        'description', 'image_url', 'body_lines', 'yaml_lines'
    )

    def __init__(self, **kw: Any) -> None:
        for k, v in kw.items():
            setattr(self, k, v)


def create_md_content_from_headings(
    file_path: str,
    grouped_headings: Dict[str, List[Tuple[str, str]]],
    page_to_section: Dict[str, str],
    group_names: Dict[str, str],
    section_first: Dict[str, str],
) -> Tuple[List[PageInfo], Dict[str, List[Tuple[str, str, str, str, str]]]]:
    """
    Split master markdown into sections at each H1. Insert YAML with breadcrumbs,
    related links, and a next link for normal sections. Collect special entries
    for features and news with optional description and image from inline YAML.
    Also parse optional tags for later SEO keywords and related links.
    Returns special entries as (title, filename, description, image_url, label).
    """
    if not os.path.exists(file_path):
        print(f"File {file_path} does not exist.")
        return [], {"features": [], "news": []}

    with open(file_path, 'r', encoding='utf-8-sig') as f:
        lines = f.read().splitlines()

    h1_pattern = re.compile(r'^\#\s+(.*?)\s*(\{(.+?)\})?\s*$')

    pages: List[PageInfo] = []
    special_entries: Dict[str, List[Tuple[str, str, str, str, str]]] = {"features": [], "news": []}

    current: PageInfo | None = None

    def parse_inline_meta(start_index: int) -> Tuple[int, Dict[str, str]]:
        """Parse inline YAML under a heading."""
        i = start_index
        if i < len(lines) and lines[i].strip() == '---':
            i += 1
            meta: Dict[str, str] = {}
            while i < len(lines) and lines[i].strip() != '---':
                line = lines[i]
                if ':' in line:
                    k, v = line.split(':', 1)
                    k = k.strip().lower()
                    v = v.strip().strip('"').strip("'")
                    meta[k] = v
                i += 1
            if i < len(lines) and lines[i].strip() == '---':
                i += 1
            return i, meta
        return start_index, {}

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        m = h1_pattern.match(line)
        if m:
            if current is not None:
                pages.append(current)
                current = None

            title_text = m.group(1).strip()
            section = m.group(3).strip() if m.group(3) else None
            sec_lower = section.lower() if section else None

            if section:
                filename = f"{slugify(section)}_{slugify(title_text)}.html"
            else:
                filename = slugify(title_text) + '.html'

            i += 1
            next_i, meta = parse_inline_meta(i)

            description = meta.get("description") or meta.get("desc") or ""
            image_url = meta.get("image") or meta.get("img") or ""
            tags_list = parse_tags_field(meta.get("tags", ""))
            tags_norm = [norm_tag(t) for t in tags_list]
            label = meta.get("label") or (tags_list[0] if tags_list else "")

            if image_url:
                image_url = f"img/{image_url}" if not image_url.startswith(("http://", "https://", "img/")) else image_url

            if sec_lower in SPECIAL_SECTIONS:
                special_entries[sec_lower].append((title_text, filename, description, image_url, label))

            yaml_lines: List[str] = []
            yaml_lines.append(f"title: {yaml_quote(title_text)}")

            # Related links and next link for normal sections
            if section and sec_lower not in SPECIAL_SECTIONS:
                links = grouped_headings.get(section, [])
                if links:
                    yaml_lines.append("links:")
                    current_idx = None
                    for idx, (url, txt) in enumerate(links):
                        if url == filename:
                            yaml_lines.append(f"- text: {yaml_quote(txt)}")
                            yaml_lines.append("  current: true")
                            current_idx = idx
                        else:
                            yaml_lines.append(f"- url: {url}")
                            yaml_lines.append(f"  text: {yaml_quote(txt)}")

                    if current_idx is not None and current_idx < len(links) - 1:
                        next_url, next_txt = links[current_idx + 1]
                        yaml_lines.append("next:")
                        yaml_lines.append(f"  url: {next_url}")
                        yaml_lines.append(f"  text: {yaml_quote(next_txt)}")

            # Breadcrumbs
            yaml_lines.append("breadcrumbs:")
            yaml_lines.append(f"- text: Home\n  url: index.html")
            if section:
                section_name = group_names.get(section, section)
                if sec_lower == "features":
                    section_url = "Features.html"
                elif sec_lower == "news":
                    section_url = "News.html"
                else:
                    section_url = section_first.get(section)
                if title_text != section_name and section_url:
                    yaml_lines.append(f"- text: {section_name}\n  url: {section_url}")
            yaml_lines.append(f"- text: {title_text}")

            body_lines: List[str] = [f"# {title_text}"]

            if sec_lower == "features" and description:
                body_lines.append(f'<p class="lead text-secondary">{html.escape(description)}</p>')

            # Feature detail hero with fixed aspect ratio and cover
            if sec_lower == "features" and image_url:
                body_lines.append(_feature_detail_styles())
                alt = html.escape(title_text, quote=True)
                figure_html = (
                    f'<figure class="feature-hero my-3 shadow-sm">'
                    f'<img src="{html.escape(image_url, quote=True)}" alt="{alt}" loading="lazy" decoding="async">'
                    '</figure>'
                )
                body_lines.append(figure_html)

            current = PageInfo(
                filename=filename,
                title=title_text,
                section=section,
                sec_lower=sec_lower,
                tags=tags_list,
                tags_norm=tags_norm,
                description=description,
                image_url=image_url,
                body_lines=body_lines,
                yaml_lines=yaml_lines,
            )

            i = next_i
            continue

        if current is not None:
            current.body_lines.append(lines[i])
        i += 1

    if current is not None:
        pages.append(current)

    return pages, special_entries


# =======================
# HTML generation
# =======================

def convert_md_to_html(md_content: str, html_filename: str, template_path: str) -> None:
    subprocess.run(
        [
            "pandoc",
            "-o", html_filename,
            "--template", template_path,
            "--include-after-body=templates/footer.html",
        ],
        input=md_content,
        text=True,
        check=True
    )

def _extract_title_from_md(md_content: str) -> str:
    for line in md_content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""

def build_related_links(pages: List[PageInfo], for_page: PageInfo, limit: int = 10) -> List[Tuple[str, str]]:
    """Return up to `limit` related pages based on overlapping tags."""
    if not for_page.tags_norm:
        return []

    candidates: List[Tuple[int, str, str]] = []  # (-overlap, title_lower, filename)
    my_tags = set(for_page.tags_norm)

    for p in pages:
        if p.filename == for_page.filename:
            continue
        if not p.tags_norm:
            continue
        overlap = len(my_tags.intersection(p.tags_norm))
        if overlap <= 0:
            continue
        candidates.append((-overlap, p.title.lower(), p.filename))

    candidates.sort()
    out: List[Tuple[str, str]] = []
    for _, _, fn in candidates[:limit]:
        for p in pages:
            if p.filename == fn:
                out.append((p.title, p.filename))
                break
    return out

def _seo_yaml_for_page(p: PageInfo) -> List[str]:
    """Add SEO-related YAML fields for article-like pages."""
    seo: List[str] = []
    seo.append(f"canonical: {yaml_quote(abs_url(p.filename))}")
    if p.description:
        seo.append(f'description: {yaml_quote(p.description)}')
    if p.image_url:
        seo.append(f'image: {yaml_quote(abs_url(p.image_url))}')
    if p.tags:
        keywords = ", ".join(p.tags)
        seo.append(f'keywords: {yaml_quote(keywords)}')
    if p.sec_lower == "news":
        seo.append('og_type: "article"')
        seo.append('schema_type: "NewsArticle"')
    else:
        seo.append('og_type: "article"')
        seo.append('schema_type: "Article"')
    return seo

def build_page_markdown(p: PageInfo, all_pages: List[PageInfo]) -> Tuple[str, str]:
    """Return (filename, md_content) for a page."""
    body = list(p.body_lines)
    yaml_lines = list(p.yaml_lines)
    yaml_lines += _seo_yaml_for_page(p)

    if p.sec_lower in SPECIAL_SECTIONS:
        related = build_related_links(all_pages, p, limit=10)
        if related:
            yaml_lines.append("links:")
            for title, url in related:
                yaml_lines.append(f"- url: {url}")
                yaml_lines.append(f"  text: {yaml_quote(title)}")

    yaml_block = "---\n" + "\n".join(yaml_lines) + "\n---"

    if p.tags:
        body.append("")
        body.append('<div class="mt-4 d-flex flex-wrap gap-2" aria-label="Tags">')
        for tag in p.tags:
            esc_tag = html.escape(tag, quote=True)
            body.append(f'<span class="badge rounded-pill bg-light text-secondary border">{esc_tag}</span>')
        body.append('</div>')

    # Wrap body lines inside a container for article content
    body_wrapped = ["<div class=\"article-content\">"] + body + ["</div>"]

    md_content = f"{yaml_block}\n\n" + "\n".join(body_wrapped)
    return p.filename, md_content

def create_all_topics(
    md_sections: List[Tuple[str, str]],
    page_to_section: Dict[str, str],
    group_names: Dict[str, str],
    section_first: Dict[str, str],
    template_path: str
) -> None:
    section_pages: Dict[str, List[Tuple[str, str]]] = {}
    for filename, md_content in md_sections:
        title = _extract_title_from_md(md_content) or os.path.splitext(filename)[0]
        sec = page_to_section.get(filename)
        if sec and sec.lower() in SPECIAL_SECTIONS:
            continue
        section = sec if sec else "Misc"
        section_pages.setdefault(section, []).append((title, filename))

    sorted_sections = sorted(section_pages.keys(), key=lambda s: s.lower())

    page_title = "All topics"
    yaml_parts = [
        f"title: {yaml_quote(page_title)}",
        f"canonical: {yaml_quote(abs_url('All_topics.html'))}",
        'og_type: "website"',
        'schema_type: "WebPage"',
        "breadcrumbs:",
        "- text: Home\n  url: index.html",
        "- text: All topics",
    ]
    yaml_block = "---\n" + "\n".join(yaml_parts) + "\n---"

    body_lines = ["# All topics", ""]
    for sec in sorted_sections:
        sec_name = group_names.get(sec, sec)
        body_lines.append(f"## {sec_name}")
        for title, filename in section_pages[sec]:
            body_lines.append(f"- [{title}]({filename})")
        body_lines.append("")

    md = f"{yaml_block}\n\n" + "\n".join(body_lines)
    convert_md_to_html(md, "All_topics.html", template_path)
    print("Created HTML file: All_topics.html")

# ===== CSS Grid styles injected where needed =====

def _feature_grid_styles() -> str:
    # Images fill their tiles regardless of any global img{height:auto}
    return """
<style>


</style>
""".strip()

def _feature_detail_styles() -> str:
    """16:9 hero that always crops correctly on feature detail pages."""
    return """
<style>

</style>
""".strip()


# ===== Grid rendering =====

def _tile_class_for_index(idx: int) -> str:
    """
    Repeating pattern to mimic an editorial mosaic.
    0: hero, 1: small, 2: small, 3: wide, 4: small, 5: tall, then repeat.
    """
    pattern = ["hero", "sm", "sm", "wide", "sm", "tall"]
    return pattern[idx % len(pattern)]

def render_feature_cards(items: List[Tuple[str, str, str, str, str]]) -> str:
    """
    Editorial mosaic grid for the front page.
    items: list of (title, filename, description, image_url, label)
    """
    def esc(s: str) -> str:
        return html.escape(s or "", quote=True)

    out: List[str] = []
    out.append(_feature_grid_styles())
    out.append('<div class="nm-grid">')

    for idx, (t, fn, desc, img, label) in enumerate(items):
        klass = _tile_class_for_index(idx)
        out.append(f'<article class="nm-tile nm-tile--{klass}">')

        out.append('<div class="nm-media-wrap">')
        if img:
            out.append(f'<img src="{esc(img)}" alt="{esc(t)}" class="nm-media">')
        else:
            out.append('<div class="nm-media" style="background:#adb5bd;height:100%"></div>')
        out.append('</div>')

        out.append('<div class="nm-overlay"></div>')

        if label:
            out.append(f'<div class="nm-ribbon">{esc(label)}</div>')

        out.append('<div class="nm-content">')
        out.append(f'<h2 class="nm-title">{esc(t)}</h2>')
        if desc:
            out.append(f'<p class="nm-desc">{esc(desc)}</p>')
        out.append('</div>')

        out.append(f'<a href="{esc(fn)}" class="stretched-link" aria-label="{esc(t)}"></a>')
        out.append('</article>')

    out.append('</div>')
    return "\n".join(out)

# ===== Helpers to ensure no trailing gap on the home mosaic =====

def _tile_width_at(index: int) -> int:
    """
    Desktop grid column width for the tile at position index (0-based).
    Pattern used by render_feature_cards: hero, sm, sm, wide, sm, tall.
    hero/wide = 8 cols, sm/tall = 4 cols on a 12-col grid.
    """
    pattern = [8, 4, 4, 8, 4, 4]
    return pattern[index % len(pattern)]

def _pick_count_for_full_row(total_items: int, target: int = 10, min_items: int = 6, grid_cols: int = 12) -> int:
    """
    Choose how many items to show so the total width of the chosen tiles
    is a multiple of grid_cols. Guarantees at least min_items if available.
    Picks a value near 'target' when several fit.
    """
    if total_items <= 0:
        return 0

    lower = min(total_items, max(min_items, 1))
    upper = total_items

    def prefix_mod(n: int) -> int:
        s = 0
        for i in range(n):
            s += _tile_width_at(i)
        return s % grid_cols

    # Candidate list around target first, then fill the rest
    base = max(lower, min(target, upper))
    probes = list(dict.fromkeys(
        [base] +
        [n for k in range(1, max(upper - lower, 1) + 1) for n in (base - k, base + k)]
    ))
    probes = [n for n in probes if lower <= n <= upper]

    for n in probes:
        if prefix_mod(n) == 0:
            return n

    # Fallback: find the n with the smallest remainder distance to a full row
    best_n = lower
    best_gap = grid_cols
    for n in range(lower, upper + 1):
        r = prefix_mod(n)
        gap = min(r, grid_cols - r)
        if gap < best_gap or (gap == best_gap and abs(n - target) < abs(best_n - target)):
            best_gap = gap
            best_n = n
    return best_n

def create_index(all_features: List[Tuple[str, str, str, str, str]]) -> None:
    """
    Build index.html from templates/index_pre.html.
    Choose a count so the last row on a 12-col grid has no whitespace.
    Always includes at least 6 items if available.
    """
    with open('templates/index_pre.html', 'r', encoding='utf-8-sig') as f:
        index_content = f.read()
    with open('templates/footer.html', 'r', encoding='utf-8-sig') as f:
        footer_content = f.read()

    feats_sorted = list(reversed(all_features)) if all_features else []
    count = _pick_count_for_full_row(len(feats_sorted), target=10, min_items=6, grid_cols=12)
    latest_features = feats_sorted[:count]

    feature_html = render_feature_cards(latest_features) if latest_features else ""
    out_html = index_content.replace('$latest_features$', feature_html).replace('$footer$', footer_content)

    with open('index.html', 'w', encoding='utf-8-sig') as f:
        f.write(out_html)
    print(f"Created index.html with {count} feature tiles (aiming to fill last row)")

def create_special_list_pages(
    kind: str,
    items: List[Tuple[str, str, str, str, str]],
    template_path: str,
    page_size: int = 12
) -> None:
    """
    Build paginated listing pages for Features or News as a mosaic grid.
    For Features, reverse the items so the last item in MD appears first.
    """
    if not items:
        return

    if kind == "features":
        items = list(reversed(items))

    def esc(s: str) -> str:
        return html.escape(s or "", quote=True)

    base_title = "Features" if kind == "features" else "News"
    base_filename = "Features" if kind == "features" else "News"

    total = len(items)
    pages = (total + page_size - 1) // page_size
    if pages == 0:
        return

    def page_filename(idx: int) -> str:
        return f"{base_filename}.html" if idx == 0 else f"{base_filename}_{idx+1}.html"

    for p in range(pages):
        start = p * page_size
        end = min(start + page_size, total)
        page_items = items[start:end]

        html_name = page_filename(p)
        title_text = base_title if p == 0 else f"{base_title} - Page {p+1}"

        yaml_lines = [
            f"title: {yaml_quote(title_text)}",
            f"canonical: {yaml_quote(abs_url(html_name))}",
            'og_type: "website"',
            'schema_type: "WebPage"',
            "breadcrumbs:",
            "- text: Home\n  url: index.html",
            f"- text: {base_title}",
        ]
        yaml_block = "---\n" + "\n".join(yaml_lines) + "\n---"

        b: List[str] = []
        b.append(_feature_grid_styles())
        b.append(f'<p class="text-uppercase text-secondary fw-semibold small mb-3">{esc(base_title)}</p>')
        b.append('<div class="nm-grid">')

        for idx, (t, fn, desc, img, label) in enumerate(page_items):
            klass = _tile_class_for_index(idx)
            b.append(f'<article class="nm-tile nm-tile--{klass}">')

            b.append('<div class="nm-media-wrap">')
            if img:
                b.append(f'<img src="{esc(img)}" alt="{esc(t)}" class="nm-media">')
            else:
                b.append('<div class="nm-media" style="background:#adb5bd;height:100%"></div>')
            b.append('</div>')

            b.append('<div class="nm-overlay"></div>')
            if label:
                b.append(f'<div class="nm-ribbon">{esc(label)}</div>')

            b.append('<div class="nm-content">')
            b.append(f'<h2 class="nm-title">{esc(t)}</h2>')
            if desc:
                b.append(f'<p class="nm-desc">{esc(desc)}</p>')
            b.append('</div>')

            b.append(f'<a href="{esc(fn)}" class="stretched-link" aria-label="{esc(t)}"></a>')
            b.append('</article>')

        b.append('</div>')

        if pages > 1:
            b.append(f'<nav aria-label="{esc(base_title)} pagination" class="mt-4">')
            b.append('<ul class="pagination">')

            def add_page(label: str, idx=None, disabled=False, active=False) -> None:
                if active:
                    b.append(f'<li class="page-item active" aria-current="page"><span class="page-link">{esc(label)}</span></li>')
                elif disabled or idx is None:
                    b.append(f'<li class="page-item disabled"><span class="page-link">{esc(label)}</span></li>')
                else:
                    b.append(f'<li class="page-item"><a class="page-link" href="{esc(page_filename(idx))}">{esc(label)}</a></li>')

            if pages <= 5:
                for i in range(pages):
                    add_page(str(i + 1), None if i == p else i, active=(i == p))
            else:
                window = 5
                half = window // 2
                start_idx = p - half
                end_idx = p + half
                if start_idx < 0:
                    end_idx += -start_idx
                    start_idx = 0
                if end_idx > pages - 1:
                    shift = end_idx - (pages - 1)
                    start_idx = max(0, start_idx - shift)
                    end_idx = pages - 1

                add_page("First", 0, disabled=(p == 0))
                for i in range(start_idx, end_idx + 1):
                    add_page(str(i + 1), None if i == p else i, active=(i == p))
                add_page("Last", pages - 1, disabled=(p == pages - 1))

            b.append('</ul>')
            b.append('</nav>')

        md = f"{yaml_block}\n\n" + "\n".join(b)
        convert_md_to_html(md, html_name, template_path)
        print(f"Created HTML file: {html_name}")

# =======================
# Orchestration
# =======================

def main():
    template_path = "templates/standard.html"

    md_dir = "master"
    md_files = sorted(glob.glob(os.path.join(md_dir, "*.md")))
    if not md_files:
        print("No .md files found in the 'master' directory.")
        return

    combined_path = "_combined_master.md"
    with open(combined_path, "w", encoding="utf-8-sig") as out:
        for i, path in enumerate(md_files):
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    content = f.read().strip()
                    if not content:
                        continue
                    if i > 0:
                        out.write("\n\n")
                    out.write(content)
                    if not content.endswith("\n"):
                        out.write("\n")
                print(f"Included: {path}")
            except OSError as e:
                print(f"Skipping {path}: {e}")

    master_md = combined_path

    grouped_headings, page_to_section, group_names, section_first = parse_headings_and_group(master_md)
    pages, special_entries = create_md_content_from_headings(
        master_md, grouped_headings, page_to_section, group_names, section_first
    )

    md_sections: List[Tuple[str, str]] = []
    expected_outputs = set()

    for p in pages:
        filename, md_content = build_page_markdown(p, pages)
        md_sections.append((filename, md_content))
        convert_md_to_html(md_content, filename, template_path)
        expected_outputs.add(filename)
        print(f"Created HTML file: {filename}")

    create_all_topics(md_sections, page_to_section, group_names, section_first, template_path)
    expected_outputs.add("All_topics.html")

    def _expected_paginated(base_filename: str, total_items: int, page_size: int = 12):
        pages_cnt = (total_items + page_size - 1) // page_size
        if pages_cnt <= 0:
            return []
        return [
            f"{base_filename}.html" if p == 0 else f"{base_filename}_{p+1}.html"
            for p in range(pages_cnt)
        ]

    feats = special_entries.get("features", [])
    news_items = special_entries.get("news", [])

    create_special_list_pages("features", feats, template_path, page_size=12)
    expected_outputs.update(_expected_paginated("Features", len(feats), page_size=12))

    create_special_list_pages("news", news_items, template_path, page_size=12)
    expected_outputs.update(_expected_paginated("News", len(news_items), page_size=12))

    # Home page: include a count that fills the last desktop row, at least 6 if available
    create_index(feats)
    expected_outputs.add("index.html")

    base_url = BASE_URL
    create_sitemap(base_url)

    current_html = set(glob.glob("*.html"))
    orphans = sorted(current_html - expected_outputs)
    for fn in orphans:
        try:
            os.remove(fn)
            print(f"Deleted orphan HTML file: {fn}")
        except OSError as e:
            print(f"Could not delete {fn}: {e}")

if __name__ == "__main__":
    main()
