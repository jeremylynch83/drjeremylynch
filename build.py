import os
import re
import subprocess
import glob   # NEW

def delete_old_html():
    """Remove any top-level .html files before regeneration."""
    for path in glob.glob("*.html"):
        try:
            os.remove(path)
            print(f"Deleted old HTML file: {path}")
        except OSError as e:
            print(f"Could not delete {path}: {e}")

def parse_headings_and_group(file_path):
    with open(file_path, 'r', encoding='utf-8-sig') as file:
        content = file.read()

    lines = content.splitlines()
    grouped_headings = {}
    section_links = {}

    heading_pattern = re.compile(r'^(#+)\s+(.*?)\s*\{(\d+)\}$')

    for line in lines:
        match = heading_pattern.match(line.strip())
        if match:
            level, text, group = match.groups()
            link  = text.replace(' ', '_') + '.html'
            group = int(group)

            grouped_headings.setdefault(group, []).append(f"- url: {link}\n  text: {text}")
            section_links[f"{level} {text}"] = group

    return grouped_headings, section_links

def create_md_content_from_headings(file_path, grouped_headings, section_links):
    if not os.path.exists(file_path):
        print(f"File {file_path} does not exist.")
        return []

    with open(file_path, 'r', encoding='utf-8-sig') as file:
        content = file.read()

    lines = content.splitlines()
    current_heading_filename = None
    current_heading_text = None
    current_text = []
    sections = []

    for line in lines:
        if line.startswith('# '):
            if current_heading_filename:
                sections.append((current_heading_filename, '\n\n'.join(current_text)))

            heading_text_raw = re.sub(r'\{.*\}$', '', line.strip())
            current_heading_filename = heading_text_raw.lstrip('#').strip().replace(' ', '_') + '.html'
            current_heading_text = "# " + heading_text_raw.lstrip('#').strip()

            if current_heading_text in section_links:
                group_number = section_links[current_heading_text]
                links_yaml = "\n".join(grouped_headings[group_number])
                yaml_block = f"---\nlinks:\n{links_yaml}\n---\n"
                current_text = [yaml_block, current_heading_text]
            else:
                current_text = [line]
        else:
            current_text.append(line)

    if current_heading_filename:
        sections.append((current_heading_filename, '\n\n'.join(current_text)))

    return sections

def create_index():
    with open('templates/index_pre.html', 'r') as f:
        index_content = f.read()
    with open('templates/footer.html', 'r') as f:
        footer_content = f.read()
    with open('index.html', 'w') as f:
        f.write(index_content.replace('$footer$', footer_content))

def convert_md_to_html(md_content, html_filename, template_path):
    with open("templates/footer.html", 'r', encoding='utf-8-sig') as file:
        footer_content = file.read()

    subprocess.run(
        ["pandoc", "-o", html_filename, "--template", template_path,
         "-V", f"footer={footer_content}"],
        input=md_content,
        text=True,
        check=True
    )

def main():
    delete_old_html()   # NEW – clear out existing HTML first

    template_path = "templates/standard.html"
    grouped_headings, section_links = parse_headings_and_group('master.md')
    md_sections = create_md_content_from_headings('master.md', grouped_headings, section_links)

    create_index()

    for filename, md_content in md_sections:
        convert_md_to_html(md_content, filename, template_path)
        print(f"Created HTML file: {filename}")

if __name__ == "__main__":
    main()
