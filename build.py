import os
import re
import glob
import subprocess
import unicodedata
import string
from typing import Dict, List, Tuple

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


def delete_all_html() -> None:
    """Delete ALL .html files in the current directory."""
    for path in glob.glob("*.html"):
        try:
            os.remove(path)
            print(f"Deleted old HTML file: {path}")
        except OSError as e:
            print(f"Could not delete {path}: {e}")


# =======================
# Parsing and grouping
# =======================

def parse_headings_and_group(file_path: str):
    """
    Parse H1 headings with '{SectionName}' to build:
      - grouped_headings: { section_label: ["- url: link\\n  text: Text", ...] }
      - section_links:    { "# Text": section_label }
      - group_names:      { section_label: section_label }
      - section_first:    { section_label: first page link }  (for breadcrumb URL)
    """
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        lines = f.read().splitlines()

    grouped_headings: Dict[str, List[str]] = {}
    section_links: Dict[str, str] = {}
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
        link = f"{slugify(section)}_{slugify(text)}.html"

        grouped_headings.setdefault(section, []).append(f"- url: {link}\n  text: {text}")
        section_links[f"# {text}"] = section

        # store first page in this section as the section breadcrumb target
        if section not in section_first:
            section_first[section] = link
        if section not in group_names:
            group_names[section] = section

    return grouped_headings, section_links, group_names, section_first


def create_md_content_from_headings(
    file_path: str,
    grouped_headings: Dict[str, List[str]],
    section_links: Dict[str, str],
    group_names: Dict[str, str],
    section_first: Dict[str, str],
) -> List[Tuple[str, str]]:
    """
    Split master.md into sections at each H1. Insert YAML with links + breadcrumbs.
    Returns list of (output_filename, markdown_content).
    """
    if not os.path.exists(file_path):
        print(f"File {file_path} does not exist.")
        return []

    with open(file_path, 'r', encoding='utf-8-sig') as f:
        lines = f.read().splitlines()

    h1_pattern = re.compile(r'^\#\s+(.*?)\s*(\{(.+?)\})?\s*$')

    sections: List[Tuple[str, str]] = []
    current_heading_filename = None
    current_text: List[str] = []

    def flush():
        nonlocal current_heading_filename, current_text
        if current_heading_filename:
            sections.append((current_heading_filename, '\n\n'.join(current_text)))
        current_text = []

    for raw in lines:
        line = raw.rstrip()
        m = h1_pattern.match(line)
        if m:
            flush()
            title_text = m.group(1).strip()
            section = m.group(3).strip() if m.group(3) else None

            # Filename with section prefix if present
            if section:
                current_heading_filename = f"{slugify(section)}_{slugify(title_text)}.html"
            else:
                current_heading_filename = slugify(title_text) + '.html'

            current_heading_text = f"# {title_text}"

            yaml_lines: List[str] = []

            # Related links (if this H1 is in a section)
            if current_heading_text in section_links:
                sec = section_links[current_heading_text]
                links_yaml = "\n".join(grouped_headings.get(sec, []))
                if links_yaml:
                    yaml_lines.append("links:")
                    yaml_lines.append(links_yaml)

            # Breadcrumbs: Home -> Section (links to that section's FIRST page) -> Page
            yaml_lines.append("breadcrumbs:")
            yaml_lines.append(f"- text: Home\n  url: index.html")
            if current_heading_text in section_links:
                sec = section_links[current_heading_text]
                section_name = group_names.get(sec, sec)
                section_url = section_first.get(sec)
                if title_text != section_name and section_url:
                    yaml_lines.append(f"- text: {section_name}\n  url: {section_url}")
            yaml_lines.append(f"- text: {title_text}")

            yaml_block = f"---\n" + "\n".join(yaml_lines) + "\n---"
            current_text = [yaml_block, current_heading_text]
        else:
            current_text.append(raw)

    flush()
    return sections


# =======================
# HTML generation
# =======================

def create_index() -> None:
    """Create index.html by replacing $footer$ in index_pre.html."""
    with open('templates/index_pre.html', 'r', encoding='utf-8-sig') as f:
        index_content = f.read()
    with open('templates/footer.html', 'r', encoding='utf-8-sig') as f:
        footer_content = f.read()
    with open('index.html', 'w', encoding='utf-8-sig') as f:
        f.write(index_content.replace('$footer$', footer_content))


def convert_md_to_html(md_content: str, html_filename: str, template_path: str) -> None:
    """Convert markdown to HTML via pandoc with template + footer include."""
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


# =======================
# Orchestration
# =======================

def main():
    master_md = 'master.md'
    template_path = "templates/standard.html"

    delete_all_html()

    grouped_headings, section_links, group_names, section_first = parse_headings_and_group(master_md)
    md_sections = create_md_content_from_headings(
        master_md, grouped_headings, section_links, group_names, section_first
    )

    create_index()

    for filename, md_content in md_sections:
        convert_md_to_html(md_content, filename, template_path)
        print(f"Created HTML file: {filename}")

if __name__ == "__main__":
    main()
