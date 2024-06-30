import os
import re
import subprocess

def parse_headings_and_group(file_path):
    with open(file_path, 'r', encoding='utf-8-sig') as file:
        content = file.read()

    lines = content.splitlines()
    grouped_headings = {}
    section_links = {}

    # Regular expression to match headings with numbers
    heading_pattern = re.compile(r'^(#+)\s+(.*?)\s*\{(\d+)\}$')

    for line in lines:
        match = heading_pattern.match(line.strip())
        if match:
            level, text, group = match.groups()
            link = text.replace(' ', '_') + '.html'
            group = int(group)

            if group not in grouped_headings:
                grouped_headings[group] = []
            grouped_headings[group].append(f"- url: {link}\n  text: {text}")

            # Store links for sections
            section_link = level + ' ' + text
            section_links[section_link] = group

    return grouped_headings, section_links

def create_md_content_from_headings(file_path, grouped_headings, section_links):
    if not os.path.exists(file_path):
        print(f"File {file_path} does not exist.")
        return []

    with open(file_path, 'r', encoding='utf-8-sig') as file:
        content = file.read()

    lines = content.splitlines()
    current_heading = None
    current_text = []
    sections = []


    for line in lines:
        if line.startswith('# '):
            print(line)
            
            if current_heading is not None:
                sections.append((current_heading, '\n\n'.join(current_text)))

            current_heading_text = re.sub(r'\{.*\}$', '', line.strip())
           
            current_heading_filename = current_heading_text.strip().lstrip('#').strip().replace(' ', '_') + '.html'
            current_heading_text = "# " + re.sub(r'\{.*\}$', '', line.strip()).strip().lstrip('#').strip()         

            # Add YAML metadata if this section belongs to a group
            if current_heading_text in section_links:
                group_number = section_links[current_heading_text]
                links_yaml = "\n".join(grouped_headings[group_number])
                yaml_block = f"---\nlinks:\n{links_yaml}\n---\n"
                current_text = [yaml_block, current_heading_text]
            else:
                current_text = [line]
            current_heading = current_heading_filename
        else:
            current_text.append(line)

    if current_heading is not None:
        sections.append((current_heading_filename, '\n\n'.join(current_text)))

    return sections

def create_index():
        # Read the content of index_pre.html
    with open('index_pre.html', 'r') as f:
        index_content = f.read()

    # Read the content of footer.html
    with open('templates/footer.html', 'r') as f:
        footer_content = f.read()

    # Replace the $footer variable with the content of footer.html
    combined_content = index_content.replace('$footer$', footer_content)

    # Write the combined content to index.html
    with open('index.html', 'w') as f:
        f.write(combined_content)

def convert_md_to_html(md_content, html_filename, template_path):
    footer_content = ""
    with open("templates/footer.html", 'r', encoding='utf-8-sig') as file:
        footer_content = file.read()
        
    process = subprocess.Popen(
        ["pandoc", "-o", html_filename, "--template", template_path, "-V", f"footer={footer_content}"],
        stdin=subprocess.PIPE,
        encoding='utf-8'
    )
    process.communicate(md_content)

def main():
    template_path = "templates/standard.html"
    grouped_headings, section_links = parse_headings_and_group('master.md')
    md_sections = create_md_content_from_headings('master.md', grouped_headings, section_links)
    
    create_index()

    for filename, md_content in md_sections:
        convert_md_to_html(md_content, filename, template_path)
        print(f"Created HTML file: {filename}")

main()
