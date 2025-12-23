import regex as re

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

# Allow common punctuation right after a macro: \rr, \rr. \rr) \rr] \rr, etc.
# (Also allow a following backslash, because \rr\setminus is common.)
FOLLOW = r"(?=\b|_|\^|\{|\}|\(|\)|\[|\]|$|\s|~|\$|\d|,|\.|;|:|!|\?|/|\\)"


# -----------------------------------------------------------------------------
# Normalization (for thm-env-capture.log style strings)
# -----------------------------------------------------------------------------

def normalize_double_backslashes(latex_source: str) -> str:
    """
    If your capture/logging pipeline produces doubled backslashes like '\\\\rr'
    (where you *intend* a single command '\\rr'), then macro expansion will miss.

    We fix that by collapsing double-backslashes ONLY when they introduce a control
    sequence name (letters or '@'):

        '\\\\rr'   -> '\\rr'
        '\\\\alpha'-> '\\alpha'
        '\\\\foo@bar' (not a LaTeX name anyway) won't match fully, but '\\\\foo' will.

    We intentionally DO NOT collapse LaTeX linebreak '\\\\' because that is usually
    followed by whitespace or punctuation, not a letter:
        '\\\\\n' stays '\\\\\n'
        '\\\\,' stays '\\\\,'
        '\\\\ ' stays '\\\\ '

    If you also see doubled escapes like '\\\\[' or '\\\\(' and want those collapsed
    too, expand the lookahead set accordingly.
    """
    return re.sub(r"\\\\(?=[A-Za-z@])", r"\\", latex_source)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def find_matching_brace(text, start_index):
    """
    Return the index of the matching '}' for the '{' at start_index.
    start_index MUST point to the opening '{'.
    """
    if start_index >= len(text) or text[start_index] != '{':
        return None

    brace_count = 0
    for i in range(start_index, len(text)):
        if text[i] == '{':
            brace_count += 1
        elif text[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                return i
    return None  # No matching brace found


def clean_up_formatting(input_string):
    """
    Removes some formatting commands from a LaTeX string. This is *not*
    semantics-preserving LaTeX; it is meant for downstream text/embedding cleanup.

    If you want the expanded output to still compile, you likely want to disable
    this (see expand_latex_macros(..., clean_definitions=False)).
    """
    patterns = [
        r"\\ensuremath",
        r"\\mathrm",
        r"\\textrm",
        r"\\mbox",
        r"\\text",
        r"\\textsc",
        r"\\mathit",
        r"\\textbf",
        r"\\textit",
        r"\\texttt",
        r"\\textsf",
        r"\\textnormal",
        r"\\textup",
        r"\\em",
        r"\\rm",
        r"\\it",
    ]

    combined_pattern = "(" + "|".join(f"({p})" for p in patterns) + ")" + r"(?=\b||\^|\{|\}|\(|\)|\[|\]|$|\s|~|\$)"
    input_string = re.sub(combined_pattern, " ", input_string)

    pattern = r"\s-?(?:\d+?\.\d+|\d+|\.\d+)\s(?:em|ex|pt|in|cm|mm|bp|dd|pc|sp|mu|mu|em|ex|\\textwidth|\\linewidth)\s*"
    input_string = re.sub(pattern, " ", input_string)

    pattern = r"(?<!%)\\texorpdfstring\s({(?:[^{}]+|(?1))})({(?:[^{}]+|(?2))*})"
    input_string = re.sub(pattern, lambda m: m.group(1)[1:-1], input_string)

    input_string = re.sub(r"\\xspace", " ", input_string)
    input_string = re.sub(r"\\!", " ", input_string)
    input_string = re.sub(r"\\[,;.:]", " ", input_string)
    input_string = re.sub(r"\{\s*\}", " ", input_string)
    input_string = re.sub(r"\\ast(?![a-zA-Z])", "*", input_string)

    # If a backslash immediately follows an alnum, separate it:
    input_string = re.sub(r"(?<=[a-zA-Z0-9])\\", r" \\", input_string)

    return input_string


def def_args_to_num_args(args):
    return len(re.findall(r"#\d", args))


def newcommand_args_to_num_args(args):
    match = re.search(r"\[(\d+)\]", args)
    return int(match.group(1)) if match else 0


def extract_definitions(text, pattern, args_to_num_args):
    """
    Extract macro definitions using a brace-matching approach for nested {} handling.

    match.end() is right after the '{' in the regex, so we use match.end()-1 as
    the index of the '{', then take the definition inside braces.
    """
    matches = {}
    for match in re.finditer(pattern, text):
        name, args = match.group(1), match.group(2)

        open_brace_idx = match.end() - 1  # points to '{'
        end = find_matching_brace(text, open_brace_idx)
        if end is not None:
            definition = text[open_brace_idx + 1 : end]  # inside braces only
            matches[f"\\{name}"] = {
                "num_args": args_to_num_args(args),
                "definition": definition
            }
    return matches


# -----------------------------------------------------------------------------
# Macro parsing
# -----------------------------------------------------------------------------

def parse_macros(latex_source):
    """
    Parses \def and \newcommand macros from LaTeX source.

    NOTE: intentionally simple (only A-Za-z macro names).
    """
    def_pattern = r"(?<!%)\\def\s*\\([A-Za-z]+)\s*((?:#\d\s*)*)\s*{"
    newcommand_pattern = r"(?<!%)\\newcommand\*?\s*{?\s*\\([A-Za-z]+)\s*}?\s*((?:\[\s*\d+\s*\])*)\s*{"
    command_mappings = extract_definitions(latex_source, def_pattern, def_args_to_num_args)
    command_mappings.update(extract_definitions(latex_source, newcommand_pattern, newcommand_args_to_num_args))
    return command_mappings


# -----------------------------------------------------------------------------
# Substitution / expansion
# -----------------------------------------------------------------------------

def sub_command_for_def(string, command, definition, num_args):
    """
    Substitute a single command in `string` with its `definition`.

    Uses function replacement so backslashes in definitions are treated literally.
    """
    if num_args > 0:
        pattern = re.escape(command)
        for i in range(num_args):
            pattern += r"\s*({(?:[^{}]|(?" + f"{i+1}" + r"))*})"
        pattern += FOLLOW

        match = re.search(pattern, string)
        while match:
            sub_for_args = {}
            for i in range(num_args):
                arg_i = match.group(i + 1)
                sub_for_args[f"#{i+1}"] = arg_i[1:-1]

            subbed_definition = re.compile(
                "|".join(re.escape(k) for k in sub_for_args.keys())
            ).sub(lambda m: sub_for_args[m.group(0)], definition)

            whole = match.group(0)
            string = re.sub(re.escape(whole), lambda _m: subbed_definition, string, count=1)
            match = re.search(pattern, string)

        return string

    else:
        pattern = re.escape(command) + FOLLOW
        return re.sub(pattern, lambda _m: definition, string)


def expand_nested_macros(command_mappings):
    """
    Expand nested user-defined macros inside macro definitions themselves.
    Removes recursive/self-referential macros.
    """
    changed = True
    while changed:
        recursive_commands = []
        changed = False

        for command in list(command_mappings.keys()):
            definition = command_mappings[command]["definition"]

            # Detect self-reference using the same FOLLOW rule
            if re.search(re.escape(command) + FOLLOW, definition):
                recursive_commands.append(command)
                continue

            old_definition = definition

            for nested_command in sorted(
                (k for k in command_mappings.keys() if k in definition),
                key=len,
                reverse=True
            ):
                if nested_command == command:
                    continue

                nested_definition = command_mappings[nested_command]["definition"]
                nested_args = command_mappings[nested_command]["num_args"]
                definition = sub_command_for_def(definition, nested_command, nested_definition, nested_args)

            if definition != old_definition:
                changed = True
                command_mappings[command]["definition"] = definition

        for command in recursive_commands:
            command_mappings.pop(command, None)

    return command_mappings


def sub_macros_for_defs(latex_source, command_mappings):
    """
    Remove macro definitions from the source, then expand macros in the remaining text.
    """
    # Remove \def definitions
    pattern = r"(?<!%)\\def\s*\\([A-Za-z]+)\s*(?:#\d\s*)*\s*({(?:[^{}]*+|(?2))*})"
    latex_source = re.sub(pattern, "", latex_source)

    # Remove \newcommand definitions
    pattern = r"(?<!%)\\newcommand\*?\s*{?\s*\\([A-Za-z]+)\s*}?\s*(?:\[\s*\d+\s*\])*\s*({(?:[^{}]*+|(?2))*})"
    latex_source = re.sub(pattern, "", latex_source)

    # Remove excessive newlines
    latex_source = re.sub(r"(?<!\\)(\n\s*){2,}", r"\1", latex_source)

    # Substitute commands longest-first to avoid partial replacement
    for command in sorted((k for k in command_mappings.keys() if k in latex_source), key=len, reverse=True):
        definition = command_mappings[command]["definition"]
        args = command_mappings[command]["num_args"]
        latex_source = sub_command_for_def(latex_source, command, definition, args)

    return latex_source


def get_command_mappings(macros_source, commands_dont_expand=None, clean_definitions=True):
    if commands_dont_expand is None:
        commands_dont_expand = []

    command_mappings = parse_macros(macros_source)

    for command in commands_dont_expand:
        command_mappings.pop(command, None)

    # Optional: clean up formatting inside macro definitions
    if clean_definitions:
        for command in list(command_mappings.keys()):
            definition = command_mappings[command]["definition"]
            command_mappings[command]["definition"] = clean_up_formatting(definition)

    command_mappings = expand_nested_macros(command_mappings)
    return command_mappings


def expand_latex_macros(
    latex_source,
    extra_macro_sources=None,
    commands_dont_expand=None,
    debug=False,
    *,
    normalize_backslashes=True,
    clean_definitions=True,
):
    """
    Expand user-defined macros in `latex_source`, optionally using `extra_macro_sources`.

    Key fix for your thm-env-capture.log workflow:
      - normalize_backslashes=True collapses '\\\\rr' -> '\\rr' (only when followed by letters/@),
        which makes expansions work even if your log serialization doubled slashes.
    """
    if extra_macro_sources is None:
        extra_macro_sources = []
    if commands_dont_expand is None:
        commands_dont_expand = []

    if normalize_backslashes:
        latex_source = normalize_double_backslashes(latex_source)
        extra_macro_sources = [normalize_double_backslashes(s) for s in extra_macro_sources]

    macros_source = latex_source + "".join(extra_macro_sources)
    command_mappings = get_command_mappings(
        macros_source,
        commands_dont_expand=commands_dont_expand,
        clean_definitions=clean_definitions,
    )

    if debug:
        print(command_mappings)

    return sub_macros_for_defs(latex_source, command_mappings)