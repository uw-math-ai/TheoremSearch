import re

_MATH_ENVS = [
    # display / alignment
    "align", "equation", "gather", "multline", "flalign", "dmath",
    "aligned", "alignedat", "split",
    # arrays & matrices
    "array", "matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix", "smallmatrix", "cases",
]

def _fix_truncated_end_braces(s: str) -> str:
    return re.sub(r'(\\end\{[A-Za-z]+(?:\*)?)(?=\s|$)', r'\1}', s)

def _balance_math_fences(s: str) -> str:
    # {}
    if len(re.findall(r'\{', s)) > len(re.findall(r'\}', s)):
        s = s.rstrip() + r'\}'
    # $$ blocks
    if s.count('$') % 2 == 1:
        s = s.rstrip() + r'$'
    # \[ \]
    if len(re.findall(r'\[', s)) > len(re.findall(r'\]', s)):
        s = s.rstrip() + r']'
    # \( \)
    if len(re.findall(r'\(', s)) > len(re.findall(r'\)', s)):
        s = s.rstrip() + r')'

    return s

def _repair_unbalanced_math(text: str) -> str:
    # normalize newlines
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # fix truncated \end{env
    text = _fix_truncated_end_braces(text)
    # make sure $$ / \[ / \( are closed
    text = _balance_math_fences(text)
    return text

def clean_latex_for_display(text: str) -> str:
    """Cleans raw LaTeX for display in Streamlit."""
    if not text:
        return text

    # Fix potential truncation errors
    text = _repair_unbalanced_math(text)

    # Remove common macros and non-important display commands
    text = re.sub(
        r"""
        \\(?:DeclareMathOperator|newcommand|renewcommand)\*?   # command
        \s*\{[^{}]+\}                                          # {name}
        (?:\s*\[\d+\])?                                        # [n] optional
        (?:\s*\[[^\]]*\])?                                     # [default] optional
        \s*\{[^{}]*\}                                          # {body} (no nesting)
        """,
        "",
        text,
        flags=re.VERBOSE | re.DOTALL,
    )

    text = re.sub(r'\\(label|ref|eqref|cite|footnote|footnotetext|alert)\{[^}]*\}', '', text)

    # Align/align* normalization
    def _normalize_align_blocks(s: str) -> str:
        out, i, n = [], 0, len(s)
        begin_pat = re.compile(r'\\begin\{align(\*)?\}', re.DOTALL)

        while i < n:
            m = begin_pat.search(s, i)
            if not m:
                out.append(s[i:])
                break

            # Copy everything before this block
            out.append(s[i:m.start()])

            star = m.group(1) or ""  # "" or "*"
            body_start = m.end()
            rest = s[body_start:]

            # Try exact end: \end{align*} or \end{align}
            exact_end = re.search(rf'\\end\{{align{re.escape(star)}\}}', rest)
            if exact_end:
                end_start_in_rest = exact_end.start()
                end_consumed = exact_end.end()
            else:
                # Fallback: accept truncated end like "\end{align*"
                trunc = re.search(rf'\\end\{{align{re.escape(star)}', rest)
                if not trunc:
                    out.append(s[m.start():])
                    break
                end_start_in_rest = trunc.start()
                end_consumed = trunc.end() + (1 if rest[trunc.end():].startswith('}') else 0)

            body = rest[:end_start_in_rest]

            # Clean the body
            body = re.sub(r'\\tag\{[^}]*\}', '', body)
            body = re.sub(r'\\(?:nonumber|notag)\b', '', body)
            body = re.sub(r'\\label\{[^}]*\}', '', body)

            # Trim trailing "\\" on the final line
            lines = [ln.rstrip() for ln in body.strip().split('\n')]
            if lines and lines[-1].endswith(r'\\'):
                lines[-1] = lines[-1][:-2].rstrip()
            cleaned = '\n'.join(lines).strip()

            # Emit a single aligned block
            out.append(f"$$\n\\begin{{aligned}}\n{cleaned}\n\\end{{aligned}}\n$$")

            # Advance past the end tag (exact or truncated)
            i = body_start + end_consumed

        return ''.join(out)

    text = _normalize_align_blocks(text)

    text = re.sub(r'\\\[\s*(.*?)\s*\\\]', r'$$\n\1\n$$', text, flags=re.DOTALL)
    text = re.sub(r'\\\(\s*(.*?)\s*\\\)', r'$\1$',       text, flags=re.DOTALL)

    # Turn \item into Markdown bullets
    text = re.sub(r'\\begin\{(?:enumerate|itemize)\}', '', text)
    text = re.sub(r'\\end\{(?:enumerate|itemize)\}',   '', text)
    text = re.sub(r'^[ \t]*\\item[ \t]*', r'- ', text, flags=re.MULTILINE)

    # Wrap "&"-aligned single lines outside existing $$...$$ blocks
    parts = re.split(r'(\$\$[\s\S]*?\$\$)', text)  # keep math blocks intact
    for i in range(0, len(parts), 2):
        segment = parts[i]
        lines = segment.split('\n')
        for j, ln in enumerate(lines):
            if '&' in ln and not ln.strip().startswith(('-', '$')):
                lines[j] = f"$$\n\\begin{{aligned}}\n{ln}\n\\end{{aligned}}\n$$"
        parts[i] = '\n'.join(lines)
    text = ''.join(parts)

    def _isolate_display_math(s: str) -> str:
        """Ensure each $$...$$ block is on its own lines with padding blank lines."""
        parts = re.split(r'(\$\$[\s\S]*?\$\$)', s)  # keep the $$...$$ blocks
        for i in range(1, len(parts), 2):  # only the $$ blocks (odd indices)
            block = parts[i]  # starts with $$, ends with $$
            # normalize interior newlines: $$\n... \n$$
            if not block.startswith('$$\n'):
                block = '$$\n' + block[2:].lstrip()
            if not block.endswith('\n$$'):
                block = block[:-2].rstrip() + '\n$$'
            parts[i] = block

            # ensure a blank line before and after the block
            if i - 1 >= 0:
                parts[i - 1] = parts[i - 1].rstrip() + '\n\n'
            if i + 1 < len(parts):
                parts[i + 1] = '\n\n' + parts[i + 1].lstrip()
        return ''.join(parts)
    text = _isolate_display_math(text)

    # Remove whitespace
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text
