"""
Section extractor for parsed paper content.

Takes ParsedContent and breaks it into logical sections based on headers.
Builds parent-child hierarchy and filters out unwanted sections.
"""

import re
from typing import Optional

from models.paper import (
    ParsedContent,
    ArxivPaperMeta,
    Section,
    Equation,
    Figure,
    Table,
)


# Common section titles to recognize
EXPECTED_SECTIONS = [
    "Abstract",
    "Introduction",
    "Related Work",
    "Background",
    "Method",
    "Methodology",
    "Approach",
    "Model",
    "Architecture",
    "Experiments",
    "Results",
    "Evaluation",
    "Discussion",
    "Conclusion",
    "Conclusions",
    "Future Work",
    "Acknowledgments",
    "Acknowledgements",
    "References",
    "Bibliography",
    "Appendix",
    "Appendices",
]

# Sections to skip (per user requirement)
SKIP_SECTIONS = [
    "References",
    "Bibliography",
    "Appendix",
    "Appendices",
    "Checklist",
    "Acknowledgment",
    "Acknowledgments",
    "Acknowledgement",
    "Acknowledgements",
    "Author Contributions",
    "Ethics Statement",
    "Broader Impact",
    "Funding",
    "Disclosure",
]

# Header patterns in markdown
HEADER_PATTERN = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)

# Numbered section pattern (e.g., "1 Introduction", "3.2 Attention", "2Related Works")
# Uses \s* after number to handle cases where no space separates number from title
NUMBERED_HEADER_PATTERN = re.compile(
    r'^(#{1,6})\s*(\d+(?:\.\d+)*\.?)\s*(\S.*)$',
    re.MULTILINE
)


def extract_sections(
    content: ParsedContent,
    meta: ArxivPaperMeta
) -> list[Section]:
    """
    Extract sections from parsed content.
    
    Args:
        content: ParsedContent with raw text and extracted elements
        meta: Paper metadata for context
        
    Returns:
        List of Section objects with hierarchy
    """
    text = content.raw_text
    
    # Find all headers
    headers = find_headers(text)
    
    if not headers:
        # No clear headers found - treat whole thing as one section
        return [Section(
            id="section-main",
            title="Main Content",
            level=1,
            content=clean_section_content(text),
            equations=content.equations,
            figures=content.figures,
            tables=content.tables,
            parent_id=None
        )]
    
    # Build sections from headers
    sections = build_sections_from_headers(headers, text, content)
    
    # Filter out unwanted sections
    sections = filter_sections(sections)
    
    # Build parent-child hierarchy
    sections = build_hierarchy(sections)

    # Add abstract if not present and available in metadata
    if meta.abstract and not any(s.title.lower() == 'abstract' for s in sections):
        abstract_section = Section(
            id="abstract",
            title="Abstract",
            level=1,
            content=meta.abstract,
            equations=[],
            figures=[],
            tables=[],
            parent_id=None
        )
        sections.insert(0, abstract_section)
    
    return sections


def find_headers(text: str) -> list[dict]:
    """
    Find all headers in markdown text.
    
    Returns list of dicts with:
    - level: header level (1-6)
    - title: header text
    - number: section number if present
    - start: start position in text
    - end: end position (start of next section)
    """
    headers = []
    
    # Find numbered headers first (more precise)
    for match in NUMBERED_HEADER_PATTERN.finditer(text):
        level = len(match.group(1))
        number = match.group(2).rstrip('.')
        title = match.group(3).strip()
        
        headers.append({
            'level': level,
            'title': title,
            'number': number,
            'start': match.start(),
            'match_end': match.end(),
        })
    
    # Find non-numbered headers
    for match in HEADER_PATTERN.finditer(text):
        level = len(match.group(1))
        title = match.group(2).strip()
        
        # Check if this is already captured as numbered
        already_found = any(
            h['start'] == match.start() for h in headers
        )
        
        if not already_found:
            # Check if title starts with a number (it's numbered but pattern didn't catch)
            # Allow zero whitespace so "2Related Works" is split into "2" + "Related Works"
            num_match = re.match(r'^(\d+(?:\.\d+)*\.?)\s*(.*\S.*)$', title)
            if num_match:
                number = num_match.group(1).rstrip('.')
                title = num_match.group(2)
            else:
                number = None
            
            headers.append({
                'level': level,
                'title': title,
                'number': number,
                'start': match.start(),
                'match_end': match.end(),
            })
    
    # Sort by position
    headers.sort(key=lambda h: h['start'])
    
    # Calculate end positions (start of next header or end of text)
    for i, header in enumerate(headers):
        if i + 1 < len(headers):
            header['end'] = headers[i + 1]['start']
        else:
            header['end'] = len(text)
    
    return headers


def build_sections_from_headers(
    headers: list[dict],
    text: str,
    content: ParsedContent
) -> list[Section]:
    """
    Build Section objects from found headers.
    """
    sections = []
    
    for i, header in enumerate(headers):
        # Generate section ID
        if header.get('number'):
            section_id = f"section-{header['number'].replace('.', '-')}"
        else:
            # Use sanitized title
            safe_title = re.sub(r'[^a-z0-9]+', '-', header['title'].lower())
            safe_title = safe_title.strip('-')[:30]
            section_id = f"section-{safe_title or i}"
        
        # Extract section content (between this header and next)
        section_start = header['match_end']
        section_end = header['end']
        section_content = text[section_start:section_end].strip()
        
        # Clean the content
        section_content = clean_section_content(section_content)
        
        # Find equations in this section
        section_equations = find_elements_in_range(
            content.equations,
            text,
            section_start,
            section_end
        )
        
        # Find figures in this section
        section_figures = find_figures_in_section(
            content.figures,
            section_content,
            header['title']
        )
        
        # Find tables in this section
        section_tables = find_tables_in_section(
            content.tables,
            section_content,
            header['title']
        )
        
        # Strip any leading section numbers (e.g. "3.2 Attention" → "Attention")
        # Use \s* so "2Related Works" → "Related Works" (no space between number and text)
        clean_title = re.sub(r'^\d+(\.\d+)*\.?\s*', '', header['title']).strip()

        sections.append(Section(
            id=section_id,
            title=clean_title or header['title'],
            level=header['level'],
            content=section_content,
            equations=section_equations,
            figures=section_figures,
            tables=section_tables,
            parent_id=None  # Will be set in build_hierarchy
        ))
    
    return sections


def clean_section_content(content: str) -> str:
    """
    Clean section content by removing artifacts.
    """
    # Remove leading/trailing whitespace
    content = content.strip()
    
    # Remove any remaining header markers at the start
    content = re.sub(r'^#{1,6}\s+.*\n', '', content)
    
    # Remove page break artifacts
    content = re.sub(r'\f', '', content)
    
    # Normalize whitespace
    content = re.sub(r'\n{3,}', '\n\n', content)
    
    # Remove common PDF artifacts
    content = re.sub(r'^\d+\s*$', '', content, flags=re.MULTILINE)  # Page numbers
    
    return content.strip()


def find_elements_in_range(
    equations: list[Equation],
    text: str,
    start: int,
    end: int
) -> list[Equation]:
    """
    Find equations whose context appears in the given text range.
    """
    section_text = text[start:end].lower()
    found = []
    
    for eq in equations:
        # Check if equation's context appears in section
        if eq.context:
            context_snippet = eq.context[:50].lower()
            if context_snippet in section_text:
                found.append(eq)
        # Also check if LaTeX appears directly
        elif eq.latex in text[start:end]:
            found.append(eq)
    
    return found


def find_figures_in_section(
    figures: list[Figure],
    section_content: str,
    section_title: str
) -> list[Figure]:
    """
    Find figures referenced in section content.
    """
    found = []
    content_lower = section_content.lower()
    
    for fig in figures:
        # Check if figure is mentioned
        fig_num = fig.id.replace('figure-', '')
        patterns = [
            f'figure {fig_num}',
            f'fig. {fig_num}',
            f'fig {fig_num}',
            fig.id,
        ]
        
        for pattern in patterns:
            if pattern.lower() in content_lower:
                found.append(fig)
                break
    
    return found


def find_tables_in_section(
    tables: list[Table],
    section_content: str,
    section_title: str
) -> list[Table]:
    """
    Find tables referenced in section content.
    """
    found = []
    content_lower = section_content.lower()
    
    for table in tables:
        # Check if table is mentioned
        table_num = table.id.replace('table-', '')
        patterns = [
            f'table {table_num}',
            table.id,
        ]
        
        for pattern in patterns:
            if pattern.lower() in content_lower:
                found.append(table)
                break
    
    return found


def filter_sections(sections: list[Section]) -> list[Section]:
    """
    Filter out unwanted sections (References, Bibliography, Acknowledgments, etc.).
    """
    filtered = []
    skip_from_here = False

    for section in sections:
        title_lower = section.title.lower().strip()

        # Check if this is a section to skip
        # Use bidirectional substring check so both
        # "Acknowledgment" in "Acknowledgments" AND
        # "Acknowledgments" in "Acknowledgment" work
        should_skip = any(
            skip.lower() in title_lower or title_lower in skip.lower()
            for skip in SKIP_SECTIONS
        )

        # Also skip appendices that come after references
        if should_skip:
            skip_from_here = True

        # Once we hit references/appendix, skip everything after
        if skip_from_here:
            continue

        if not should_skip:
            filtered.append(section)

    return filtered


def build_hierarchy(sections: list[Section]) -> list[Section]:
    """
    Build parent-child hierarchy based on header levels.
    """
    if not sections:
        return sections
    
    # Stack to track parent sections at each level
    parent_stack: list[Optional[Section]] = [None] * 7  # Levels 0-6
    
    for section in sections:
        level = section.level
        
        # Find parent (closest section with lower level)
        parent = None
        for i in range(level - 1, 0, -1):
            if parent_stack[i]:
                parent = parent_stack[i]
                break
        
        if parent:
            section.parent_id = parent.id
        
        # Update stack
        parent_stack[level] = section
        
        # Clear deeper levels (they're no longer valid parents)
        for i in range(level + 1, 7):
            parent_stack[i] = None
    
    return sections


def consolidate_sections(sections: list[Section]) -> list[Section]:
    """
    Merge subsections into their top-level parents.

    Reduces 30-100+ sections to ~5-12 top-level sections.
    Subsection content is appended under bold subheading markers
    so no information is lost, but the section count drops dramatically.
    """
    if len(sections) <= 12:
        return sections

    # Build parent → children map
    children_map: dict[str | None, list[Section]] = {}
    for s in sections:
        children_map.setdefault(s.parent_id, []).append(s)

    # Find root sections (parent_id=None)
    roots = [s for s in sections if s.parent_id is None]

    if not roots:
        return sections  # Flat structure, no hierarchy to merge

    # If there's only 1 root (e.g. the paper title at h1), it would
    # swallow the entire paper.  Step down to its direct children instead.
    if len(roots) == 1 and roots[0].id in children_map:
        single_root = roots[0]
        roots = children_map[single_root.id]
        # Re-parent: these children are now the new roots
        for r in roots:
            r.parent_id = None

    def _collect_descendants(section_id: str) -> list[Section]:
        """DFS collect all descendants in document order."""
        result = []
        for child in children_map.get(section_id, []):
            if child in roots:
                continue  # Don't collect fellow roots as descendants
            result.append(child)
            result.extend(_collect_descendants(child.id))
        return result

    consolidated = []
    for root in roots:
        descendants = _collect_descendants(root.id)

        if not descendants:
            consolidated.append(root)
            continue

        # Merge content: root content + each descendant as a subheading
        merged_parts = [root.content]
        merged_equations = list(root.equations)
        merged_figures = list(root.figures)
        merged_tables = list(root.tables)

        for desc in descendants:
            merged_parts.append(f"\n\n**{desc.title}**\n\n{desc.content}")
            merged_equations.extend(desc.equations)
            merged_figures.extend(desc.figures)
            merged_tables.extend(desc.tables)

        consolidated.append(Section(
            id=root.id,
            title=root.title,
            level=root.level,
            content="\n".join(merged_parts),
            equations=merged_equations,
            figures=merged_figures,
            tables=merged_tables,
            parent_id=None,
        ))

    return consolidated


def detect_paper_structure(text: str) -> dict:
    """
    Detect the overall structure/type of paper.
    
    Returns dict with:
    - has_clear_sections: bool
    - section_style: 'numbered', 'titled', 'mixed', 'none'
    - detected_sections: list of section names found
    """
    headers = find_headers(text)
    
    if not headers:
        return {
            'has_clear_sections': False,
            'section_style': 'none',
            'detected_sections': []
        }
    
    # Check section style
    numbered_count = sum(1 for h in headers if h.get('number'))
    titled_count = len(headers) - numbered_count
    
    if numbered_count > titled_count:
        style = 'numbered'
    elif titled_count > numbered_count:
        style = 'titled'
    else:
        style = 'mixed'
    
    # Find standard sections
    detected = []
    for header in headers:
        title_lower = header['title'].lower()
        for expected in EXPECTED_SECTIONS:
            if expected.lower() in title_lower:
                detected.append(expected)
                break
    
    return {
        'has_clear_sections': len(headers) >= 3,
        'section_style': style,
        'detected_sections': detected
    }
