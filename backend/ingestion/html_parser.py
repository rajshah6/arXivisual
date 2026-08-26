"""
HTML parser for ar5iv papers.

ar5iv provides HTML versions of arXiv papers with clean structure:
- LaTeX preserved in <math> tags
- Clean <section>, <h2>, etc. structure
- Better than PDF parsing for structure preservation
"""

import re

import httpx
from bs4 import BeautifulSoup, NavigableString

from models.paper import Equation, Figure, ParsedContent, Table


async def fetch_and_parse_html(html_url: str) -> ParsedContent:
    """
    Fetch and parse ar5iv HTML content.
    
    Args:
        html_url: ar5iv URL (e.g., "https://ar5iv.org/abs/1706.03762")
        
    Returns:
        ParsedContent with extracted content
    """
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(html_url)
        response.raise_for_status()
        html_content = response.text
    
    return parse_html(html_content)


def parse_html(html_content: str) -> ParsedContent:
    """
    Parse ar5iv HTML content into structured format.
    
    Args:
        html_content: Raw HTML string
        
    Returns:
        ParsedContent with extracted content
    """
    soup = BeautifulSoup(html_content, 'lxml')
    
    # Find the main article content
    article = soup.find('article') or soup.find('main') or soup.find('body')
    
    if not article:
        raise ValueError("Could not find article content in HTML")
    
    # Extract equations from math tags
    equations = extract_equations_from_html(article)
    
    # Extract figures
    figures = extract_figures_from_html(article)
    
    # Extract tables
    tables = extract_tables_from_html(article)
    
    # Convert to markdown-like text
    raw_text = convert_to_markdown(article)
    
    return ParsedContent(
        raw_text=raw_text,
        equations=equations,
        figures=figures,
        tables=tables
    )


def extract_equations_from_html(soup: BeautifulSoup) -> list[Equation]:
    """
    Extract LaTeX equations from ar5iv HTML.
    
    ar5iv preserves LaTeX in various ways:
    - <math> tags with alttext attribute containing LaTeX
    - <script type="math/tex"> tags
    - <span class="ltx_Math"> elements
    """
    equations = []
    seen_latex = set()
    
    # Method 1: Find <math> tags with alttext
    for math_tag in soup.find_all('math'):
        latex = math_tag.get('alttext', '')
        
        if not latex:
            # Try to find annotation-xml with LaTeX
            annotation = math_tag.find('annotation', encoding='application/x-tex')
            if annotation:
                latex = annotation.get_text()
        
        if latex and latex not in seen_latex:
            seen_latex.add(latex)
            
            # Determine if inline or display
            display = math_tag.get('display', 'inline')
            is_inline = display == 'inline'
            
            # Get context from parent
            context = get_surrounding_text(math_tag, max_chars=100)
            
            equations.append(Equation(
                latex=latex.strip(),
                context=context,
                is_inline=is_inline
            ))
    
    # Method 2: Find script tags with math/tex type
    for script in soup.find_all('script', type=re.compile(r'math/tex')):
        latex = script.get_text()
        
        if latex and latex not in seen_latex:
            seen_latex.add(latex)
            
            # Check if display mode from type attribute
            script_type = script.get('type', '')
            is_inline = 'display' not in script_type
            
            context = get_surrounding_text(script, max_chars=100)
            
            equations.append(Equation(
                latex=latex.strip(),
                context=context,
                is_inline=is_inline
            ))
    
    # Method 3: Find ltx_equation class elements
    for eq_div in soup.find_all(class_=re.compile(r'ltx_equation|ltx_eqn')):
        # Look for math inside
        math_tag = eq_div.find('math')
        if math_tag:
            latex = math_tag.get('alttext', '')
            if not latex:
                annotation = math_tag.find('annotation', encoding='application/x-tex')
                if annotation:
                    latex = annotation.get_text()
            
            if latex and latex not in seen_latex:
                seen_latex.add(latex)
                context = get_surrounding_text(eq_div, max_chars=100)
                
                equations.append(Equation(
                    latex=latex.strip(),
                    context=context,
                    is_inline=False  # ltx_equation is typically display
                ))
    
    return equations


def extract_figures_from_html(soup: BeautifulSoup) -> list[Figure]:
    """
    Extract figures from ar5iv HTML.
    """
    figures = []
    seen_ids = set()
    
    # Find figure elements
    for idx, fig in enumerate(soup.find_all('figure'), 1):
        # Get figure ID
        fig_id = fig.get('id', f'figure-{idx}')
        if not fig_id.startswith('figure'):
            fig_id = f"figure-{idx}"
        
        if fig_id in seen_ids:
            continue
        seen_ids.add(fig_id)
        
        # Get caption
        caption_elem = fig.find('figcaption')
        caption = caption_elem.get_text(strip=True) if caption_elem else ""
        
        # Clean up caption (remove "Figure X:" prefix)
        caption = re.sub(r'^(?:Figure|Fig\.?)\s*\d+[:\.]?\s*', '', caption, flags=re.IGNORECASE)
        
        figures.append(Figure(
            id=fig_id,
            caption=caption,
            page=0  # HTML doesn't have page numbers
        ))
    
    # Also look for ltx_figure class (LaTeXML output)
    for idx, fig in enumerate(soup.find_all(class_='ltx_figure'), len(figures) + 1):
        fig_id = fig.get('id', f'figure-{idx}')
        
        if fig_id in seen_ids:
            continue
        seen_ids.add(fig_id)
        
        caption_elem = fig.find(class_='ltx_caption')
        caption = caption_elem.get_text(strip=True) if caption_elem else ""
        caption = re.sub(r'^(?:Figure|Fig\.?)\s*\d+[:\.]?\s*', '', caption, flags=re.IGNORECASE)
        
        figures.append(Figure(
            id=fig_id,
            caption=caption,
            page=0
        ))
    
    return figures


def extract_tables_from_html(soup: BeautifulSoup) -> list[Table]:
    """
    Extract tables from ar5iv HTML with structure.
    """
    tables = []
    seen_ids = set()
    
    for idx, table_elem in enumerate(soup.find_all('table'), 1):
        # Skip navigation/layout tables
        table_class = ' '.join(table_elem.get('class', []))
        if 'nav' in table_class.lower() or 'layout' in table_class.lower():
            continue
        
        # Get table ID
        table_id = table_elem.get('id', f'table-{idx}')
        if table_id in seen_ids:
            continue
        seen_ids.add(table_id)
        
        # Look for caption
        caption = ""
        caption_elem = table_elem.find('caption')
        if caption_elem:
            caption = caption_elem.get_text(strip=True)
            caption = re.sub(r'^(?:Table)\s*\d+[:\.]?\s*', '', caption, flags=re.IGNORECASE)
        
        # Also check parent for ltx_table with caption
        parent = table_elem.parent
        if parent and 'ltx_table' in ' '.join(parent.get('class', [])):
            parent_caption = parent.find(class_='ltx_caption')
            if parent_caption:
                caption = parent_caption.get_text(strip=True)
                caption = re.sub(r'^(?:Table)\s*\d+[:\.]?\s*', '', caption, flags=re.IGNORECASE)
        
        # Extract headers and rows
        headers = []
        rows = []
        
        # Find header row
        thead = table_elem.find('thead')
        if thead:
            header_row = thead.find('tr')
            if header_row:
                headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
        
        # If no thead, first row might be headers
        if not headers:
            first_row = table_elem.find('tr')
            if first_row and first_row.find('th'):
                headers = [th.get_text(strip=True) for th in first_row.find_all(['th', 'td'])]
        
        # Find data rows
        tbody = table_elem.find('tbody') or table_elem
        for tr in tbody.find_all('tr'):
            # Skip header row if we already got it
            if tr.find('th') and not rows and headers:
                continue
            
            row_data = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
            if row_data and any(cell for cell in row_data):  # Skip empty rows
                rows.append(row_data)
        
        if headers or rows:
            tables.append(Table(
                id=table_id,
                caption=caption,
                headers=headers,
                rows=rows
            ))
    
    return tables


def get_surrounding_text(element, max_chars: int = 100) -> str:
    """
    Get text surrounding an element for context.
    """
    context_parts = []
    
    # Get text before
    prev_sibling = element.previous_sibling
    while prev_sibling and len(''.join(context_parts)) < max_chars:
        if isinstance(prev_sibling, NavigableString):
            text = str(prev_sibling).strip()
            if text:
                context_parts.insert(0, text)
        elif hasattr(prev_sibling, 'get_text'):
            text = prev_sibling.get_text(strip=True)
            if text:
                context_parts.insert(0, text)
        prev_sibling = prev_sibling.previous_sibling
    
    # Get text after
    next_sibling = element.next_sibling
    while next_sibling and len(''.join(context_parts)) < max_chars * 2:
        if isinstance(next_sibling, NavigableString):
            text = str(next_sibling).strip()
            if text:
                context_parts.append(text)
        elif hasattr(next_sibling, 'get_text'):
            text = next_sibling.get_text(strip=True)
            if text:
                context_parts.append(text)
        next_sibling = next_sibling.next_sibling
    
    context = ' '.join(context_parts)
    return context[:max_chars * 2] if context else ""


def convert_to_markdown(soup: BeautifulSoup) -> str:
    """
    Convert ar5iv HTML to markdown-like text.
    
    Preserves:
    - Headers as # markdown
    - Paragraphs
    - LaTeX math with proper delimiters ($...$ for inline, $$...$$ for display)
    - Basic formatting
    """
    lines = []
    
    # Process sections and content
    for element in soup.descendants:
        if element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            level = int(element.name[1])
            text = extract_text_with_math(element)
            if text:
                lines.append('')
                lines.append('#' * level + ' ' + text)
                lines.append('')
        
        elif element.name == 'p':
            text = extract_text_with_math(element)
            if text:
                lines.append(text)
                lines.append('')
        
        elif element.name == 'section':
            # Get section title if available
            title = element.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            if title:
                extract_text_with_math(title)
                sec_class = ' '.join(element.get('class', []))
                
                # Determine level from class or header
                if 'ltx_section' in sec_class:
                    level = 2
                elif 'ltx_subsection' in sec_class:
                    level = 3
                elif 'ltx_subsubsection' in sec_class:
                    level = 4
                else:
                    level = int(title.name[1]) if title.name else 2
    
    # Join and clean up
    text = '\n'.join(lines)
    
    # Remove excessive blank lines
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    
    return text.strip()


def extract_text_with_math(element) -> str:
    """
    Extract text from an element while preserving LaTeX math with proper delimiters.
    
    - Inline math gets wrapped with $...$
    - Display math gets wrapped with $$...$$
    """
    if element is None:
        return ""
    
    parts = []
    
    for child in element.children:
        if isinstance(child, NavigableString):
            # Regular text
            text = str(child)
            if text.strip():
                parts.append(text)
        elif child.name == 'math':
            # Math element - extract LaTeX and wrap appropriately
            latex = child.get('alttext', '')
            if not latex:
                # Try annotation
                annotation = child.find('annotation', encoding='application/x-tex')
                if annotation:
                    latex = annotation.get_text()
            
            if latex:
                latex = latex.strip()
                # Check if display or inline math
                display = child.get('display', 'inline')
                if display == 'block':
                    parts.append(f'\n\n$${latex}$$\n\n')
                else:
                    parts.append(f'${latex}$')
            else:
                # Fallback to text content
                parts.append(child.get_text())
        elif child.name == 'script' and 'math/tex' in child.get('type', ''):
            # Script tag with LaTeX
            latex = child.get_text().strip()
            if latex:
                script_type = child.get('type', '')
                if 'display' in script_type:
                    parts.append(f'\n\n$${latex}$$\n\n')
                else:
                    parts.append(f'${latex}$')
        elif child.name in ['span', 'cite', 'a', 'em', 'strong', 'b', 'i']:
            # Inline elements - recurse
            inner = extract_text_with_math(child)
            if inner:
                if child.name in ['em', 'i']:
                    parts.append(f'*{inner}*')
                elif child.name in ['strong', 'b']:
                    parts.append(f'**{inner}**')
                else:
                    parts.append(inner)
        elif child.name and hasattr(child, 'children'):
            # Other elements with children - recurse
            inner = extract_text_with_math(child)
            if inner:
                parts.append(inner)
    
    result = ''.join(parts)
    # Clean up spacing around math
    result = re.sub(r'\s+(\$[^$]+\$)\s+', r' \1 ', result)
    result = re.sub(r'\s{2,}', ' ', result)
    return result.strip()
