"""
PDF parser for extracting structured content from arXiv papers.

Uses pymupdf4llm for LLM-ready markdown output with good equation handling.
"""

import io
import re

import fitz  # PyMuPDF
import pymupdf4llm

from models.paper import Equation, Figure, ParsedContent, Table

# Regex patterns for extraction
DISPLAY_EQUATION_PATTERN = re.compile(
    r'\$\$(.+?)\$\$|'  # $$...$$ (display)
    r'\\begin\{equation\*?\}(.+?)\\end\{equation\*?\}|'  # \begin{equation}...\end{equation}
    r'\\begin\{align\*?\}(.+?)\\end\{align\*?\}|'  # \begin{align}...\end{align}
    r'\\begin\{eqnarray\*?\}(.+?)\\end\{eqnarray\*?\}|'  # \begin{eqnarray}...\end{eqnarray}
    r'\\begin\{gather\*?\}(.+?)\\end\{gather\*?\}|'  # \begin{gather}...\end{gather}
    r'\\begin\{multline\*?\}(.+?)\\end\{multline\*?\}|'  # \begin{multline}...\end{multline}
    r'\\\[(.+?)\\\]',  # \[...\]
    re.DOTALL
)

INLINE_EQUATION_PATTERN = re.compile(
    r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)|'  # $...$ (inline, not $$)
    r'\\\\?\((.+?)\\\\?\)',  # \(...\) inline math
    re.DOTALL
)

# Header patterns for PDF section detection
PDF_HEADER_PATTERNS = [
    # Numbered sections: "1 Introduction", "3.2 Methods"
    re.compile(r'^[#*]*\s*(\d+(?:\.\d+)*\.?)\s+([A-Z][A-Za-z\s]+)$', re.MULTILINE),
    # Bold headers: **Introduction**
    re.compile(r'^\*\*([A-Z][A-Za-z\s]+)\*\*$', re.MULTILINE),
    # All caps headers: INTRODUCTION
    re.compile(r'^([A-Z][A-Z\s]{3,})$', re.MULTILINE),
    # Markdown headers: # Introduction, ## Methods
    re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE),
]

FIGURE_PATTERN = re.compile(
    r'(?:Figure|Fig\.?)\s*(\d+(?:\.\d+)?)[:\.]?\s*([^\n]+)?',
    re.IGNORECASE
)

TABLE_CAPTION_PATTERN = re.compile(
    r'(?:Table)\s*(\d+(?:\.\d+)?)[:\.]?\s*([^\n]+)?',
    re.IGNORECASE
)


def parse_pdf(pdf_bytes: bytes) -> ParsedContent:
    """
    Parse PDF content into structured format.
    
    Args:
        pdf_bytes: Raw PDF file bytes
        
    Returns:
        ParsedContent with extracted text, equations, figures, and tables
    """
    # Convert bytes to file-like object for PyMuPDF
    pdf_stream = io.BytesIO(pdf_bytes)
    
    # Open PDF with PyMuPDF
    doc = fitz.open(stream=pdf_stream, filetype="pdf")
    
    # Use pymupdf4llm for markdown conversion
    md_text = pymupdf4llm.to_markdown(doc)
    
    # Clean the text
    cleaned_text = clean_pdf_text(md_text)
    
    # Extract equations
    equations = extract_equations(cleaned_text)
    
    # Extract figures
    figures = extract_figures(cleaned_text, doc)
    
    # Extract tables
    tables = extract_tables(cleaned_text, doc)
    
    doc.close()
    
    return ParsedContent(
        raw_text=cleaned_text,
        equations=equations,
        figures=figures,
        tables=tables
    )


def clean_pdf_text(text: str) -> str:
    """
    Clean PDF-extracted text by removing artifacts and improving structure.
    
    Removes:
    - Page numbers
    - Running headers/footers
    - Excessive whitespace
    - Common PDF artifacts
    
    Adds:
    - Markdown headers for detected section titles
    """
    lines = text.split('\n')
    cleaned_lines = []
    
    for _i, line in enumerate(lines):
        stripped = line.strip()
        
        # Skip likely page numbers (standalone numbers)
        if re.match(r'^\s*\d+\s*$', stripped):
            continue
        
        # Skip common header patterns (arXiv identifier lines)
        if re.match(r'^\s*arXiv:\d+\.\d+v?\d*\s*\[', stripped):
            continue
        
        # Skip lines that are just dashes or underscores (separators)
        if re.match(r'^[\-_=]{5,}$', stripped):
            continue
        
        # Detect and convert section headers
        converted_line = convert_to_markdown_header(stripped)
        if converted_line:
            cleaned_lines.append('')  # Add blank line before header
            cleaned_lines.append(converted_line)
            cleaned_lines.append('')  # Add blank line after header
        else:
            cleaned_lines.append(line)
    
    # Join and clean up excessive whitespace
    text = '\n'.join(cleaned_lines)
    
    # Remove excessive blank lines (more than 2 consecutive)
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    
    # Fix common OCR/extraction issues
    text = text.replace('ﬁ', 'fi')
    text = text.replace('ﬂ', 'fl')
    text = text.replace('ﬀ', 'ff')
    
    return text.strip()


def convert_to_markdown_header(line: str) -> str | None:
    """
    Convert a line to markdown header if it looks like a section title.
    
    Returns:
        Markdown header string if detected, None otherwise
    """
    if not line or len(line) > 100:  # Headers are typically short
        return None
    
    # Check for numbered section headers: "1 Introduction", "3.2 Methods"
    numbered_match = re.match(r'^(\d+(?:\.\d+)*\.?)\s+([A-Z][A-Za-z\s,\-:]+)$', line)
    if numbered_match:
        number = numbered_match.group(1).rstrip('.')
        title = numbered_match.group(2).strip()
        # Determine level by number of dots
        level = min(number.count('.') + 2, 6)  # Start at h2 for "1 Intro", h3 for "1.1 Sub"
        return f"{'#' * level} {number} {title}"
    
    # Check for bold markdown headers: **Introduction**
    bold_match = re.match(r'^\*\*([A-Z][A-Za-z\s,\-:]+)\*\*$', line)
    if bold_match:
        title = bold_match.group(1).strip()
        return f"## {title}"
    
    # Check for ALL CAPS headers (common in PDFs)
    if line.isupper() and len(line) > 3 and len(line.split()) <= 6:
        # Skip common non-header all-caps like "BLEU", "GPU", etc.
        if len(line) > 10:  # Likely a real header
            return f"## {line.title()}"
    
    # Check for "Abstract" specifically (common first section)
    if line.lower() == 'abstract':
        return "## Abstract"
    
    return None


def extract_equations(text: str) -> list[Equation]:
    """
    Extract LaTeX equations from text.
    
    Args:
        text: Markdown text potentially containing LaTeX
        
    Returns:
        List of Equation objects
    """
    equations = []
    seen_latex = set()  # Avoid duplicates
    
    # Extract display equations
    for match in DISPLAY_EQUATION_PATTERN.finditer(text):
        # Get the first non-None group (different patterns)
        latex = None
        for group in match.groups():
            if group:
                latex = group.strip()
                break
        
        if latex and latex not in seen_latex:
            seen_latex.add(latex)
            
            # Get surrounding context (100 chars before and after)
            start = max(0, match.start() - 100)
            end = min(len(text), match.end() + 100)
            context = text[start:end].strip()
            
            equations.append(Equation(
                latex=latex,
                context=context,
                is_inline=False
            ))
    
    # Extract inline equations
    for match in INLINE_EQUATION_PATTERN.finditer(text):
        # Get the first non-None group
        latex = None
        for group in match.groups():
            if group:
                latex = group.strip()
                break
        
        if not latex or latex in seen_latex:
            continue
        
        # Skip very short matches (likely false positives like currency)
        if len(latex) < 3:
            continue
        
        # Skip if it looks like plain text or a number
        if latex.isalnum() or latex.replace('.', '').replace(',', '').isdigit():
            continue
        
        seen_latex.add(latex)
        
        # Get surrounding context
        start = max(0, match.start() - 50)
        end = min(len(text), match.end() + 50)
        context = text[start:end].strip()
        
        equations.append(Equation(
            latex=latex,
            context=context,
            is_inline=True
        ))
    
    # Also look for Unicode math symbols that might indicate equations
    # This helps catch equations that weren't properly converted to LaTeX
    math_symbol_pattern = re.compile(
        r'([A-Za-z]+\s*[=≈≠<>≤≥∈∉⊂⊃∪∩]\s*[^,.\n]{3,50})'
    )
    for match in math_symbol_pattern.finditer(text):
        potential_eq = match.group(1).strip()
        if potential_eq not in seen_latex and len(potential_eq) > 5:
            # Only add if it looks equation-like
            if any(c in potential_eq for c in '=≈≠<>≤≥∈∉⊂⊃∪∩∑∏∫'):
                seen_latex.add(potential_eq)
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                context = text[start:end].strip()
                
                equations.append(Equation(
                    latex=potential_eq,
                    context=context,
                    is_inline=True
                ))
    
    return equations


def extract_figures(text: str, doc: fitz.Document | None = None) -> list[Figure]:
    """
    Extract figure references and captions from text.
    
    Args:
        text: Markdown text
        doc: Optional PyMuPDF document for page detection
        
    Returns:
        List of Figure objects
    """
    figures = []
    seen_ids = set()
    
    for match in FIGURE_PATTERN.finditer(text):
        fig_num = match.group(1)
        caption = match.group(2) or ""
        
        fig_id = f"figure-{fig_num}"
        
        # Skip duplicates
        if fig_id in seen_ids:
            continue
        seen_ids.add(fig_id)
        
        # Try to determine page number (approximate from position in text)
        page = 0
        if doc:
            # Rough estimate: position in text / total length * total pages
            position_ratio = match.start() / len(text)
            page = int(position_ratio * doc.page_count) + 1
        
        figures.append(Figure(
            id=fig_id,
            caption=caption.strip(),
            page=page
        ))
    
    return figures


def extract_tables(text: str, doc: fitz.Document | None = None) -> list[Table]:
    """
    Extract tables from PDF.
    
    This is a basic implementation that extracts table captions.
    For full table structure, would need more sophisticated parsing.
    
    Args:
        text: Markdown text
        doc: Optional PyMuPDF document for table extraction
        
    Returns:
        List of Table objects
    """
    tables = []
    seen_ids = set()
    
    # First, find table captions
    for match in TABLE_CAPTION_PATTERN.finditer(text):
        table_num = match.group(1)
        caption = match.group(2) or ""
        
        table_id = f"table-{table_num}"
        
        if table_id in seen_ids:
            continue
        seen_ids.add(table_id)
        
        tables.append(Table(
            id=table_id,
            caption=caption.strip(),
            headers=[],
            rows=[]
        ))
    
    # Try to extract actual table content using PyMuPDF
    if doc:
        for page_num in range(doc.page_count):
            page = doc[page_num]
            
            # Find tables on page
            try:
                page_tables = page.find_tables()
                
                for idx, table in enumerate(page_tables):
                    # Extract table data
                    table_data = table.extract()
                    
                    if table_data and len(table_data) > 0:
                        headers = table_data[0] if table_data else []
                        rows = table_data[1:] if len(table_data) > 1 else []
                        
                        # Clean up None values
                        headers = [str(h) if h else "" for h in headers]
                        rows = [[str(cell) if cell else "" for cell in row] for row in rows]
                        
                        # Find matching table or create new one
                        table_id = f"table-page{page_num + 1}-{idx + 1}"
                        
                        # Check if we have a caption-matched table we can enhance
                        matched = False
                        for existing_table in tables:
                            if not existing_table.headers and not existing_table.rows:
                                existing_table.headers = headers
                                existing_table.rows = rows
                                matched = True
                                break
                        
                        if not matched and headers:
                            tables.append(Table(
                                id=table_id,
                                caption="",
                                headers=headers,
                                rows=rows
                            ))
            except Exception:
                # Table extraction can fail, continue with other pages
                continue
    
    return tables


def parse_pdf_from_path(pdf_path: str) -> ParsedContent:
    """
    Parse PDF from file path.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        ParsedContent with extracted content
    """
    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()
    return parse_pdf(pdf_bytes)
