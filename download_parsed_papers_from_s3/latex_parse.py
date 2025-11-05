import regex
import bisect
import theorem_forms
import json
import argparse
import os
from typing import Pattern
from patterns import *

# TODO:
#   more regex for different versions of macros:
#       \NewDocumentCommand, will require its own method
#   \renew commands
#   \input from other files in TeX source
#   remove newlines from theorem statements


def _scanner(pat: Pattern, data: str, ) -> list:
    """
    Returns a list of regex matches based on a specified pattern
    """
    theorems = list(regex.finditer(pat, data, regex.VERBOSE | regex.DOTALL | regex.MULTILINE, overlapped=True))
    return theorems


def def_handling(data: str) -> str:
    """
    Translates user-defined \\def macros (a LaTeX primitive) back into their raw LaTeX definitions
    """
    translation = {}
    macros = _scanner(NEWDEF, data)

    for item in macros:
        params = (item.group('params') or "").count('#')
        translation[item.group('name')] = (params, item.group('body'))

    for key in sorted(translation.keys(), key=len, reverse=True):
        assemble = regex.escape(rf"{key}") + r"(?:(?=[^A-Za-z@])|(?=\s*\{))"
        assemble = assemble + "".join(
            fr"\s*\{{(?P<arg_{i}>[^{{}}]*)\}}"   # capture anything not { or }
            for i in range(1, translation[key][0]+1)
        )
        captures = _scanner(assemble, data)
        for item in captures:
            new_cmd = translation[key][1]
            old_cmd = regex.escape(rf"{key}") + r"(?:(?=[^A-Za-z@])|(?=\s*\{))"
            for j in range(len(item.groups())):
                old_cmd += r"\s*\{" + regex.escape(item.group(j+1)) + r"\}"
                new_cmd = new_cmd.replace(rf"#{j+1}", item.group(j+1))
            data = regex.sub(old_cmd, lambda _m: new_cmd, data)

    return data


def alias_handling(data: str) -> str:
    """
    Translates alias counters in source document so theorems can be properly counted.
    (See: TeX \\newaliascnt)
    """
    translation = {}
    replacements = []

    aliases = _scanner(NEWALIASCNT, data)
    for item in aliases:
        translation[item.group(1)] = item.group(2)
    
    matches = _scanner(NEWTHEOREM, data)
    matches.extend(_scanner(NEWDECLARETHEOREM, data))

    if translation:
        for m in matches:
            if m.group('shared') is None:
                continue
            shared = m.group('shared')

            start, end = m.span('shared')
            new_shared = translation[shared]
            replacements.append((start, end, new_shared))

    for start, end, repl in sorted(replacements, key=lambda x: x[0], reverse=True): # backward to ensure indices line up
        data = data[:start] + repl + data[end:]

    return data


def macro_handling(data: str) -> str:
    """
    Translates user-defined \\def macros (a LaTeX primitive) back into their raw LaTeX definitions
    """
    translation = {}

    data = operator_handling(data) # replace dec. math operators
    macros = _scanner(NEWCOMMAND, data)

    for item in macros:
        params = int(item.group('num_args') or "0")
        translation[item.group('macro_name')] = (params, item.group('body'))

    for key in sorted(translation.keys(), key=len, reverse=True):
        assemble = regex.escape(rf"{key}") + r"(?:(?=[^A-Za-z@])|(?=\s*\{))"
        assemble = assemble + "".join(
            fr"\s*\{{(?P<arg_{i}>[^{{}}]*)\}}"   # capture anything not { or }
            for i in range(1, translation[key][0]+1)
        )
        captures = _scanner(assemble, data)
        
        for item in captures:
            new_cmd = translation[key][1]
            old_cmd = regex.escape(rf"{key}") + r"(?:(?=[^A-Za-z@])|(?=\s*\{))"
            for j in range(len(item.groups())):
                old_cmd += r"\s*\{" + regex.escape(item.group(j+1)) + r"\}"
                new_cmd = new_cmd.replace(rf"#{j+1}", item.group(j+1))
            data = regex.sub(old_cmd, lambda _m: new_cmd, data)
    return data


def operator_handling(data: str) -> str:
    """
    Replaces operator Commands with raw text
    (See: TeX \\DeclareMathOperator)
    """
    translation = {}
    macros = _scanner(NEWMATHOPERATOR, data)

    for item in macros:
        translation[item.group('cmd')] = item.group('text')

    for key in sorted(translation.keys(), key=len, reverse=True):
        data = regex.sub(rf"{regex.escape(key)}(?![A-Za-z])", regex.escape(rf"\\text{{{translation[key]}}}"), data)
    return data


def environment_handling(data: str) -> str:
    """
    Translates user-defined environments back to normal and countable forms
    (See: TeX \\newenvironment)
    """
    cmds = []

    thms_list = _scanner(NEWTHEOREM, data)
    thms_list.extend(_scanner(NEWDECLARETHEOREM, data))
    for item in thms_list:
        cmds.append(item)

    envs = _scanner(NEWENVIRONMENT, data)
    for m in envs:
        name = m.group('name')
        begin_cmd = m.group('begin')
        end_cmd = m.group('end')

        for c in cmds:
            if '\\' + c.group('env') in begin_cmd:
                new_theorem_command = (
                    f"\\newtheorem{c.group('star') or ''}"
                    f"{{{name}}}"
                    f"{('[' + c.group('shared') + ']') if c.group('shared') else ''}"
                    f"{{{c.group('title')}}}"
                    f"{('[' + c.group('within') + ']') if c.group('within') else ''}"
                )
                data = data + new_theorem_command # add new theorem definition to data

    return data


def locate_theorems(data: str) -> tuple[str, dict, dict, regex.Scanner]:
    """
    Locates and splits theorems into sets based on position and numeration
    (numbered, non-numbered, appendix)
    """
    theorem_locations = []
    theorem_names = []

    m = regex.search(r"\\begin\{appendix\}", data) # locate the appendix, if it exists
    n = regex.search(r"\\appendix", data)

    appendix = None
    if m:
        appendix = m.start()
    elif n:
        appendix = n.start()

    thm_scan = _scanner(NEWTHEOREM, data)
    thm_scan.extend(_scanner(NEWDECLARETHEOREM, data))
    for theoremtype in thm_scan:
        locator = _scanner(SPECIFICTHEOREM(theoremtype.group('env')), data)
        for t in locator:
            theorem_locations.append(t.start())
            theorem_names.append(theoremtype.group('env'))

    theorem_names = [v for _, v in sorted(zip(theorem_locations, theorem_names))]
    theorem_locations.sort()

    # split remaining by main and appendix
    if appendix:
        cutoff = bisect.bisect_left(theorem_locations, appendix)
        theorem_names, appendix_names = theorem_names[:cutoff], theorem_names[cutoff:]
        theorem_locations, appendix_locations = theorem_locations[:cutoff], theorem_locations[cutoff:] # defining and calling
        appx = dict(zip(appendix_locations, appendix_names))
    else:
        appx = {}

    thms = dict(zip(theorem_locations, theorem_names))

    return data, thms, appx, thm_scan


def label_theorems(theorems: dict, thm_scan: regex.Scanner, is_appendix: bool, data: str) -> list: # update for numbering appendix theorems
    """
    Labels theorems based on their specified counters
    """
    # find beginning of doc
    begin_doc = _scanner(r"\\begin\{document\}", data)[0].start()

    # gather sections
    section_locations = []
    sections = _scanner(NEWSECTION, data)
    for s in sections:
        if s.group(1) == "*" or s.start() < begin_doc:
            continue
        section_locations.append(s.start())
    sctns = dict(zip(section_locations, ["section"] * len(section_locations)))

    cur = len(section_locations)

    sections = _scanner(NEWSUBSECTION, data)
    for s in sections:
        if s.group(1) == "*" or s.start() < begin_doc:
            continue
        section_locations.append(s.start())
    sctns = sctns | dict(zip(section_locations[cur:], ["subsection"] * (len(section_locations) - cur)))

    cur = len(section_locations)

    sections = _scanner(NEWSUBSUBSECTION, data)
    for s in sections:
        if s.group(1) == "*" or s.start() < begin_doc:
            continue
        section_locations.append(s.start())
    sctns = sctns | dict(zip(section_locations[cur:], ["subsubsection"] * (len(section_locations) - cur)))

    tn = theorem_forms.TheoremNumberer()

    if is_appendix:
        m = regex.search(r"\\begin\{appendix\}", data) # locate the appendix, if it exists
        n = regex.search(r"\\appendix", data)

        appendix = None
        if m:
            appendix = m.start()
        elif n:
            appendix = n.start()

        if appendix:
            tn.in_appendix = True
            i = bisect.bisect_left(section_locations, appendix)
            for idx in section_locations[:i]:
                sctns.pop(idx)

    # check counters
    counter = _scanner(NEWNUMBERWITHIN, data)
    for item in counter:
        tn.numberwithin(item.group("child"), item.group("parent"))

    # load theorem commands into numberer
    for item in thm_scan:
        if 'BRACED' in item.groupdict().keys():
            starred, env, shared, title, within = None, item.group("env"), item.group("shared"), item.group("title"), item.group("within")
        else:
            starred, env, shared, title, within = item.groupdict().values()
            
        if starred == "*":
            starred = True
        tn.define_newtheorem(starred, env, shared, title, within)

    labels = sctns | theorems

    res = []

    for item in sorted(labels):
        if labels[item] == "section":
            tn.increment("section")
        elif labels[item] == "subsection":
            tn.increment("subsection")
        elif labels[item] == "subsubsection":
            tn.increment("subsubsection")
        else:
            res.append(tn.begin(labels[item]))

    return res


def bundle_theorems(thm_scan: regex.Scanner, data: str, num_thms: list, app_thms: list=None) -> list:
    
    res = []
    num_list = []

    # grab theorem envs
    for item in thm_scan:
        num_list.append(item.group('env'))

    # setup statements for parsing
    for t in num_list:
        data = regex.sub(rf"\\begin\s*\{{{t}\*?\}}", r"\\begin{theorem}", data)
        data = regex.sub(rf"\\end\s*\{{{t}\*?\}}", r"\\end{theorem}", data)

    # parse and add to lists
    theorems = _scanner(STATEMENTBODY, data)

    labeled_thms = grab_labels(theorems)

    print(len(num_thms), len(labeled_thms))
    for i in range(len(num_thms)):
        res.append((num_thms[i],) + labeled_thms[i])
    for i in range(len(theorems) - len(num_thms)):
        res.append((app_thms[i],) + labeled_thms[i + len(num_thms)])
    return res


def grab_labels(theorems: regex.Scanner) -> list:
    """
    Extracts labels from theorem statements when present
    """
    res = []
    captured = []
    h = 0
    for item in reversed(theorems):
        h += 1
        t = item.group(0)
        t = t[15:-13] # removes \begin{theorem} and \end{theorem}
        t = regex.sub(r'\s*\n\s*', ' ', t) # get rid of newlines in body
        label = regex.search(NEWLABEL, t)
        if label and (lbl := label.group('label')):
            if lbl in captured:
                t = t.replace(r"\label{" + lbl + r"}", "")
                res.append((t, None))
                continue
            t = t.replace(r"\label{" + lbl + r"}", "")
            captured.append(lbl)
            res.append((t, lbl))
        else:
            res.append((t, None))

    res.reverse()
    return res


def extract(filename: str) -> dict:
    with open(filename, 'r', encoding="utf-8", errors="replace") as file:
        data = file.read()

        # remove any comments, single or multiline
        data = regex.sub(r"(?<!\\)%.*", "", data)
        data = regex.sub(r'\\begin\{comment\}.*?\\end\{comment\}', '', data, flags=regex.DOTALL)

        # translation of various user-defined macros
        data = def_handling(data)
        data = alias_handling(data)
        data = macro_handling(data)
        data = environment_handling(data)

        # locate and split theorems
        data, num_thms, appx_thms, thm_scan = locate_theorems(data)

        # label theorems accordingly
        num_thms = label_theorems(num_thms, thm_scan, False, data)
        
        appx_thms = label_theorems(appx_thms, thm_scan, True, data)

        # bundle results
        return bundle_theorems(thm_scan, data, num_thms, appx_thms)


# if you want to run it standalone
if __name__ == "__main__":
    THM_DIR = "./parsed_papers"
    if not os.path.exists(THM_DIR):
        os.makedirs(THM_DIR)

    parser = argparse.ArgumentParser(description="Extract mathematical statements from .tex files")
    parser.add_argument(
        "--filepath", 
        type=str, 
        required=True, 
        help="The filepath to your .tex document (e.g. 'lorem_ipsum.tex')"
    )
    args = parser.parse_args()
    output = os.path.join(THM_DIR, args.filepath)

    x = extract(args.filepath)

    data = [{"theorem": thm, "body": body, "label": label} for thm, body, label in x]
    with open(output.replace('.tex', '.json'), 'w') as f:
        json.dump(data, f, indent=4) # minor note: '\' gets printed as '\\' in json