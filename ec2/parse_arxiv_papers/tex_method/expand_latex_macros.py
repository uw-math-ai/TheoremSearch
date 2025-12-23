import regex as re

# Finds the matching closing brace for a given opening brace index.
def find_matching_brace(text, start_index):
    brace_count = 1
    for i in range(start_index, len(text)):
        if text[i] == '{':
            brace_count += 1
        elif text[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                return i
    return None  # No matching brace found

# Removes all formatting commands from a LaTeX string
def clean_up_formatting(input_string):
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
        r"\\it"
    ]

    combined_pattern = "(" + "|".join(f'({p})' for p in patterns) + ")" + r"(?=\b||\^|\{|\}|\(|\)|\[|\]|$|\s|~|\$)"
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
    input_string = re.sub(r'(?<=[a-zA-Z0-9])\\', r" \\", input_string)

    return input_string

# Counts the number of arguments (#1, #2, ...) in a \def macro.
def def_args_to_num_args(args):
    return len(re.findall(r"#\d", args))

# Counts the number of arguments from a \newcommand declaration.
def newcommand_args_to_num_args(args):
    match = re.search(r"\[(\d+)\]", args)
    return int(match.group(1)) if match else 0

# Extracts macro definitions using a stack-based approach for nested {} handling.
def extract_definitions(text, pattern, args_to_num_args):
    matches = {}
    for match in re.finditer(pattern, text):
        name, args = match.group(1), match.group(2)
        start = match.end()
        end = find_matching_brace(text, start)
        if end:
            definition = text[start:end]
            matches[f"\\{name}"] = {
                "num_args": args_to_num_args(args),
                "definition": definition
            }
    return matches

# Parses \def and \newcommand macros from LaTeX source.
def parse_macros(latex_source):
    # Patterns for \def and \newcommand
    def_pattern = r"(?<!%)\\def\s*\\([A-Za-z]+)\s*((?:#\d\s*)*)\s*{"
    newcommand_pattern = r"(?<!%)\\newcommand\*?\s*{?\s*\\([A-Za-z]+)\s*}?\s*((?:\[\s*\d+\s*\])*)\s*{"
    command_mappings = extract_definitions(latex_source, def_pattern, def_args_to_num_args)
    command_mappings.update(extract_definitions(latex_source, newcommand_pattern, newcommand_args_to_num_args))
    return command_mappings

def sub_command_for_def(string, command, definition, num_args):
    # Expanded follow-set: allow common punctuation right after a macro, e.g. \qq, \rr. \pp;
    FOLLOW = r"(?=\b|_|\^|\{|\}|\(|\)|\[|\]|$|\s|~|\$|\d|,|\.|;|:|!|\?|/)"
    
    # If command definition uses args
    if num_args > 0:
        pattern = re.escape(command)
        for i in range(num_args):
            pattern += r"\s*({(?:[^{}]|(?" + f"{i+1}" + r"))*})"
        pattern += FOLLOW

        match = re.search(pattern, string)
        while match:
            sub_for_args = {}
            for i in range(num_args):
                arg_i = match.group(i+1)
                sub_for_args[f"#{i+1}"] = arg_i[1:-1]

            subbed_definition = re.compile(
                "|".join(re.escape(key) for key in sub_for_args.keys())
            ).sub(lambda m: sub_for_args[m.group(0)], definition)

            subbed_definition = subbed_definition.replace('\\', '\\\\')
            string = re.sub(re.escape(match.group(0)), subbed_definition, string)
            match = re.search(pattern, string)

        return string

    # If no args
    else:
        pattern = re.escape(command) + FOLLOW
        definition = definition.replace('\\', '\\\\')
        return re.sub(pattern, definition, string)

def expand_nested_macros(command_mappings):
    # since some user-defined commands may make reference to other user-defined
    # commands, loop through the dictionary until all commands are expanded back into raw LaTeX
    changed = True
    while changed:
        recursive_commands = []
        # assume no changes need to be made
        changed = False
        for command in command_mappings:
            definition = command_mappings[command]['definition']
            if re.search(re.escape(command) + r"(?=\b|_|\^|\{|\}|\(|\)|\[|\]|$|\s|~|\$|\d)", definition):
                recursive_commands.append(command)
                continue
            # Sort by inverse length to prevent accidental replacements of \\command_longname by \\command
            old_definition = definition
            for nested_command in sorted(filter(lambda key : key in definition, command_mappings.keys()), key=len, reverse=True):
                # This module cannot handle recursive commands
                if nested_command == command:
                    continue
                # replace all nested user-defined commands
                else:
                    nested_definition = command_mappings[nested_command]['definition']
                    nested_args = command_mappings[nested_command]['num_args']
                    new_definition = sub_command_for_def(definition, nested_command, nested_definition, nested_args)
                    definition = new_definition
            # Check that the substitution actually worked, because sometimes it does not
            if definition != old_definition:
                changed = True
                command_mappings[command]['definition'] = definition
        [command_mappings.pop(command, None) for command in recursive_commands]  
                
    return command_mappings

def sub_macros_for_defs(latex_source, command_mappings):
    # Remove all macro definitions from source
    pattern = r"(?<!%)\\def\s*\\([A-Za-z]+)\s*(?:#\d\s*)*\s*({(?:[^{}]*+|(?2))*})"
    latex_source = re.sub(pattern, "", latex_source)
    pattern = r"(?<!%)\\newcommand\*?\s*{?\s*\\([A-Za-z]+)\s*}?\s*(?:\[\s*\d+\s*\])*\s*({(?:[^{}]*+|(?2))*})"
    latex_source = re.sub(pattern, "", latex_source)
    # Remove excessive newlines
    latex_source = re.sub(r'(?<!\\)(\n\s*){2,}', r'\1', latex_source)
    for command in sorted(filter(lambda key : key in latex_source, command_mappings.keys()), key=len, reverse=True):
        definition = command_mappings[command]['definition']
        args = command_mappings[command]['num_args']
        latex_source = sub_command_for_def(latex_source, command, definition, args)
    return latex_source

def get_command_mappings(macros_source, commands_dont_expand=[]):
    command_mappings = parse_macros(macros_source)
    
    for command in commands_dont_expand:
        command_mappings.pop(command, None)
    
    for command in command_mappings:
        definition = command_mappings[command]["definition"]
        clean_definition = clean_up_formatting(definition)
        command_mappings[command]["definition"] = clean_definition

    command_mappings = expand_nested_macros(command_mappings)
    return command_mappings

def expand_latex_macros(latex_source, extra_macro_sources=[], commands_dont_expand=[]):
    macros_source = latex_source
    for source in extra_macro_sources:
        macros_source += source

    command_mappings = get_command_mappings(macros_source, commands_dont_expand)

    return sub_macros_for_defs(latex_source, command_mappings)