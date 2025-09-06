import os
import re
import glob
import subprocess
import unicodedata
import string
import html
from datetime import datetime, timezone
from typing import Dict, List, Tuple

# Optional environment override for base URL
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://www.drjeremylynch.com/")

SPECIAL_SECTIONS = {"features", "news"}

# =======================
# Utilities
# =======================

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

def delete_all_html() -> None:
    """Delete ALL .html files in the current directory."""
    for path in glob.glob("*.html"):
        try:
            os.remove(path)
            print(f"Deleted old HTML file: {path}")
        except OSError as e:
            print(f"Could not delete {path}: {e}")

def display_section_name(section: str) -> str:
    """Pretty display name for a section label."""
    if section.lower() == "features":
        return "Features"
    if section.lower() == "news":
        return "News"
    return section

def create_sitemap(base_url: str) -> None:
    """
    Create sitemap.xml for all generated .html files in the current directory.
    Uses file modification time for <lastmod>.
    """
    # Ensure scheme and trailing slash
    if not base_url.startswith(("http://", "https://")):
        base_url = "https://" + base_url
    if not base_url.endswith('/'):
        base_url += '/'

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

        # Map page to section
        page_to_section[link] = section

        # Display names
        group_names.setdefault(section, display_section_name(section))

        # Special sections do not get related link groups
        if sec_lower not in SPECIAL_SECTIONS:
            grouped_headings.setdefault(section, []).append((link, text))

        # Section breadcrumb target
        if section not in section_first:
            if sec_lower == "features":
                section_first[section] = "Features.html"
            elif sec_lower == "news":
                section_first[section] = "News.html"
            else:
                section_first[section] = link

    return grouped_headings, page_to_section, group_names, section_first


def create_md_content_from_headings(
    file_path: str,
    grouped_headings: Dict[str, List[Tuple[str, str]]],
    page_to_section: Dict[str, str],
    group_names: Dict[str, str],
    section_first: Dict[str, str],
) -> Tuple[List[Tuple[str, str]], Dict[str, List[Tuple[str, str, str, str]]]]:
    """
    Split master markdown into sections at each H1. Insert YAML with breadcrumbs,
    related links, and a next link for normal sections. Collects special entries
    for features and news with optional description and image in a simple YAML
    block directly under the H1.
    """
    if not os.path.exists(file_path):
        print(f"File {file_path} does not exist.")
        return [], {"features": [], "news": []}

    with open(file_path, 'r', encoding='utf-8-sig') as f:
        lines = f.read().splitlines()

    h1_pattern = re.compile(r'^\#\s+(.*?)\s*(\{(.+?)\})?\s*$')

    sections: List[Tuple[str, str]] = []
    special_entries: Dict[str, List[Tuple[str, str, str, str]]] = {"features": [], "news": []}

    current_heading_filename = None
    current_text: List[str] = []

    def flush():
        nonlocal current_heading_filename, current_text
        if current_heading_filename:
            sections.append((current_heading_filename, '\n\n'.join(current_text)))
        current_heading_filename = None
        current_text = []

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
            flush()

            title_text = m.group(1).strip()
            section = m.group(3).strip() if m.group(3) else None
            sec_lower = section.lower() if section else None

            if section:
                current_heading_filename = f"{slugify(section)}_{slugify(title_text)}.html"
            else:
                current_heading_filename = slugify(title_text) + '.html'

            i += 1
            next_i, meta = parse_inline_meta(i)
            description = meta.get("description") or meta.get("desc") or ""
            image_url = meta.get("image") or meta.get("img") or ""
            if image_url:
                image_url = f"img/{image_url}"

            if sec_lower in SPECIAL_SECTIONS:
                special_entries[sec_lower].append((title_text, current_heading_filename, description, image_url))

            yaml_lines: List[str] = []
            yaml_lines.append(f"title: {yaml_quote(title_text)}")

            # Related links and next link for normal sections
            if section and sec_lower not in SPECIAL_SECTIONS:
                links = grouped_headings.get(section, [])
                if links:
                    yaml_lines.append("links:")
                    current_idx = None
                    for idx, (url, txt) in enumerate(links):
                        if url == current_heading_filename:
                            yaml_lines.append(f"- text: {yaml_quote(txt)}")
                            yaml_lines.append("  current: true")
                            current_idx = idx
                        else:
                            yaml_lines.append(f"- url: {url}")
                            yaml_lines.append(f"  text: {yaml_quote(txt)}")

                    # Next mapping except for the last item in the section
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

            yaml_block = f"---\n" + "\n".join(yaml_lines) + "\n---"
            current_text = [yaml_block, f"# {title_text}"]

            # Add description text under H1 for features
            if sec_lower == "features" and description:
                current_text.append(f'<p class="lead text-secondary">{html.escape(description)}</p>')

            # If a Feature has an image, show it under the description
            if sec_lower == "features" and image_url:
                alt = html.escape(title_text, quote=True)
                figure_html = (
                    f'<figure class="my-3">'
                    f'<img src="{html.escape(image_url, quote=True)}" alt="{alt}" class="img-fluid rounded shadow-sm w-100">'
                    '</figure>'
                )
                current_text.append(figure_html)





            i = next_i
            continue

        if current_heading_filename is not None:
            current_text.append(lines[i])
        i += 1

    flush()
    return sections, special_entries


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

    yaml_block = (
        "---\n"
        f"title: {yaml_quote('All topics')}\n"
        "breadcrumbs:\n"
        "- text: Home\n  url: index.html\n"
        "- text: All topics\n"
        "---"
    )

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

def render_feature_cards(items: List[Tuple[str, str, str, str]]) -> str:
    """
    Render a list of features for the front page.
    Adds a divider between items, not after the last one.
    items: list of (title, filename, description, image_url)
    """
    out: List[str] = []
    total = len(items)
    for idx, (t, fn, desc, img) in enumerate(items):
        is_last = (idx == total - 1)
        row_classes = "row g-4 align-items-center mb-4 pb-3"
        if not is_last:
            row_classes += " border-bottom"

        out.append(f'<article class="{row_classes}">')
        if img:
            out.append('<div class="col-md-6">')
            out.append('<div class="ratio ratio-16x9">')
            out.append(f'<a href="{html.escape(fn)}"><img src="{html.escape(img)}" alt="{html.escape(t)}" class="img-fluid rounded shadow-sm w-100 h-100 object-fit-cover"></a>')
            out.append('</div></div>')
            out.append('<div class="col-md-6">')
        else:
            out.append('<div class="col-12">')

        out.append('<h2 class="h4 fw-bold mb-2">')
        out.append(f'<a href="{html.escape(fn)}" class="link-dark text-decoration-none">{html.escape(t)}</a>')
        out.append('</h2>')
        if desc:
            out.append(f'<p class="text-secondary mb-0 small">{html.escape(desc)}</p>')
        out.append('</div></article>')
    return "\n".join(out)


def create_index(latest_features: List[Tuple[str, str, str, str]]) -> None:
    """
    Build index.html from templates/index_pre.html, inserting:
      - $latest_features$  replaced with rendered latest features
      - $footer$           replaced with templates/footer.html
    """
    with open('templates/index_pre.html', 'r', encoding='utf-8-sig') as f:
        index_content = f.read()
    with open('templates/footer.html', 'r', encoding='utf-8-sig') as f:
        footer_content = f.read()

    feature_html = render_feature_cards(latest_features) if latest_features else ""
    out_html = index_content.replace('$latest_features$', feature_html).replace('$footer$', footer_content)

    with open('index.html', 'w', encoding='utf-8-sig') as f:
        f.write(out_html)
    print("Created index.html with latest features")

def create_special_list_pages(
    kind: str,
    items: List[Tuple[str, str, str, str]],
    template_path: str,
    page_size: int = 5
) -> None:
    """
    Build paginated listing pages for Features or News.
    Every item renders as a hero-style row with optional image.
    For Features, reverse the items so the last item in MD appears first.
    """
    if not items:
        return

    # Reverse Features ordering
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

        yaml_block = (
            "---\n"
            f"title: {yaml_quote(title_text)}\n"
            "breadcrumbs:\n"
            "- text: Home\n  url: index.html\n"
            f"- text: {base_title}\n"
            "---"
        )

        b: List[str] = []
        b.append(f'<p class="text-uppercase text-secondary fw-semibold small mb-2">{esc(base_title)}</p>')

        # Items: treat every item as a hero row
        for t, fn, desc, img in page_items:
            b.append('<article class="row g-4 align-items-center mb-4 pb-3 border-bottom">')

            if img:
                b.append('<div class="col-md-6">')
                b.append('<div class="ratio ratio-16x9">')
                b.append(f'<a href="{esc(fn)}"><img src="{esc(img)}" alt="{esc(t)}" class="img-fluid rounded shadow-sm w-100 h-100 object-fit-cover"></a>')
                b.append('</div></div>')
                b.append('<div class="col-md-6">')
            else:
                b.append('<div class="col-12">')

            b.append('<h2 class="h4 fw-bold mb-2">')
            b.append(f'<a href="{esc(fn)}" class="link-dark text-decoration-none">{esc(t)}</a>')
            b.append('</h2>')
            if desc:
                b.append(f'<p class="text-secondary mb-0 small">{esc(desc)}</p>')
            b.append('</div></article>')

        # Pagination
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
    delete_all_html()

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
    md_sections, special_entries = create_md_content_from_headings(
        master_md, grouped_headings, page_to_section, group_names, section_first
    )

    # Create article pages
    for filename, md_content in md_sections:
        convert_md_to_html(md_content, filename, template_path)
        print(f"Created HTML file: {filename}")

    # Create All topics
    create_all_topics(md_sections, page_to_section, group_names, section_first, template_path)

    # Create special listing pages with H2, optional image, and description
    create_special_list_pages("features", special_entries.get("features", []), template_path, page_size=5)
    create_special_list_pages("news", special_entries.get("news", []), template_path, page_size=5)

    # Build index.html with latest three features
    feats = special_entries.get("features", [])
    latest_features = list(reversed(feats))[:3] if feats else []
    create_index(latest_features)

    # Build sitemap.xml
    base_url = SITE_BASE_URL.rstrip('/') + '/'
    create_sitemap(base_url)

if __name__ == "__main__":
    main()
