import regex
import bisect
from . import theorem_forms
import json
import argparse
import os
from typing import Pattern
from .patterns import *

# TODO: How to handle '\noindent {\bf Proposition 4}. {\it For the BM ... are related as:}'?

DEFAULT_THEOREM_ENVS = ["theorem", "lemma", "proposition", "corollary", "claim", "definition", "remark", "example"]

def _scanner(pat: Pattern, data: str) -> list:
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
            fr"\s*\{{(?P<arg_{i}>[^{{}}]*)\}}"
            for i in range(1, translation[key][0] + 1)
        )
        captures = _scanner(assemble, data)
        for item in captures:
            new_cmd = translation[key][1]
            old_cmd = regex.escape(rf"{key}") + r"(?:(?=[^A-Za-z@])|(?=\s*\{))"
            for j in range(len(item.groups())):
                old_cmd += r"\s*\{" + regex.escape(item.group(j + 1)) + r"\}"
                new_cmd = new_cmd.replace(rf"#{j + 1}", item.group(j + 1))
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
            if shared not in translation:
                continue

            start, end = m.span('shared')
            new_shared = translation[shared]
            replacements.append((start, end, new_shared))

    for start, end, repl in sorted(replacements, key=lambda x: x[0], reverse=True):
        data = data[:start] + repl + data[end:]

    return data


def macro_handling(data: str) -> str:
    """
    Translates user-defined \\def macros (a LaTeX primitive) back into their raw LaTeX definitions
    """
    translation = {}

    data = operator_handling(data)
    macros = _scanner(NEWCOMMAND, data)

    for item in macros:
        params = int(item.group('num_args') or "0")
        translation[item.group('macro_name')] = (params, item.group('body'))

    for key in sorted(translation.keys(), key=len, reverse=True):
        assemble = regex.escape(rf"{key}") + r"(?:(?=[^A-Za-z@])|(?=\s*\{))"
        assemble = assemble + "".join(
            fr"\s*\{{(?P<arg_{i}>[^{{}}]*)\}}"
            for i in range(1, translation[key][0] + 1)
        )
        captures = _scanner(assemble, data)

        for item in captures:
            new_cmd = translation[key][1]
            old_cmd = regex.escape(rf"{key}") + r"(?:(?=[^A-Za-z@])|(?=\s*\{))"
            for j in range(len(item.groups())):
                old_cmd += r"\s*\{" + regex.escape(item.group(j + 1)) + r"\}"
                new_cmd = new_cmd.replace(rf"#{j + 1}", item.group(j + 1))
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
                data = data + new_theorem_command

    return data


def locate_theorems(data: str) -> tuple[str, dict, dict, regex.Scanner]:
    """
    Locates and splits theorems into sets based on position and numeration
    (numbered, non-numbered, appendix)
    """
    theorem_locations = []
    theorem_names = []

    m = regex.search(r"\\begin\{appendix\}", data)
    appendix = m.start() if m else None

    thm_scan = _scanner(NEWTHEOREM, data)
    thm_scan.extend(_scanner(NEWDECLARETHEOREM, data))

    if thm_scan:
        for theoremtype in thm_scan:
            env = theoremtype.group("env")
            locator = _scanner(SPECIFICTHEOREM(env), data)

            for t in locator:
                theorem_locations.append(t.start())
                theorem_names.append(env)
    else:
        for env in DEFAULT_THEOREM_ENVS:
            locator = _scanner(SPECIFICTHEOREM(env), data)
            for t in locator:
                theorem_locations.append(t.start())
                theorem_names.append(env)

    theorem_names = [v for _, v in sorted(zip(theorem_locations, theorem_names))]
    theorem_locations.sort()

    if appendix:
        cutoff = bisect.bisect_left(theorem_locations, appendix)
        theorem_names, appendix_names = theorem_names[:cutoff], theorem_names[cutoff:]
        theorem_locations, appendix_locations = theorem_locations[:cutoff], theorem_locations[cutoff:]
        appx = dict(zip(appendix_locations, appendix_names))
    else:
        appx = {}

    thms = dict(zip(theorem_locations, theorem_names))

    return data, thms, appx, thm_scan


def label_theorems(theorems: dict, thm_scan: regex.Scanner, is_appendix: bool, data: str) -> list:
    """
    Labels theorems based on their specified counters
    """
    begin_matches = _scanner(r"\\begin\{document\}", data)

    if begin_matches:
        begin_doc = begin_matches[0].start()
    else:
        begin_doc = 0

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
        m = regex.search(r"\\begin\{appendix\}", data)
        appendix = m.start() if m else None

        if appendix:
            tn.in_appendix = True
            i = bisect.bisect_left(section_locations, appendix)
            for idx in section_locations[:i]:
                sctns.pop(idx)

    counter = _scanner(NEWNUMBERWITHIN, data)
    for item in counter:
        tn.numberwithin(item.group("child"), item.group("parent"))

    if thm_scan:
        for item in thm_scan:
            if 'BRACED' in item.groupdict().keys():
                starred, env, shared, title, within = None, item.group("env"), item.group("shared"), item.group("title"), item.group("within")
            else:
                starred, env, shared, title, within = item.groupdict().values()

            if starred == "*":
                starred = True

            if title is None or title.strip() == "":
                title = env.capitalize()

            tn.define_newtheorem(starred, env, shared, title, within)
    else:
        envs = sorted(set(theorems.values()))
        for env in envs:
            title = env.capitalize()
            tn.define_newtheorem(False, env, None, title, None)

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


def bundle_theorems(thm_scan: regex.Scanner, data: str, num_thms: list, app_thms: list = None) -> list:
    res = []
    num_list = []

    if app_thms is None:
        app_thms = []

    if thm_scan:
        for item in thm_scan:
            num_list.append(item.group('env'))
    else:
        num_list = DEFAULT_THEOREM_ENVS.copy()

    for t in num_list:
        data = regex.sub(rf"\\begin\s*\{{{t}\*?\}}", r"\\begin{theorem}", data)
        data = regex.sub(rf"\\end\s*\{{{t}\*?\}}", r"\\end{theorem}", data)

    theorems = _scanner(STATEMENTBODY, data)

    labeled_thms = grab_labels(theorems)

    n_main = min(len(num_thms), len(labeled_thms))
    for i in range(n_main):
        res.append((num_thms[i],) + labeled_thms[i])

    remaining_labeled = len(labeled_thms) - n_main
    remaining_theorems = len(theorems) - n_main
    n_app = min(remaining_theorems, remaining_labeled, len(app_thms))

    for i in range(n_app):
        res.append((app_thms[i],) + labeled_thms[n_main + i])
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
        t = t[15:-13]
        t = regex.sub(r'\s*\n\s*', ' ', t)
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

        data = regex.sub(r"(?<!\\)%.*", "", data)
        data = regex.sub(r'\\begin\{comment\}.*?\\end\{comment\}', '', data, flags=regex.DOTALL)

        data = def_handling(data)
        data = alias_handling(data)
        data = macro_handling(data)
        data = environment_handling(data)

        # normalize any begin/end-like macros
        data = regex.sub(r"\\beg[a-zA-Z]*\s*\{([^{}]+)\}", r"\\begin{\1}", data)
        data = regex.sub(r"\\end[a-zA-Z]*\s*\{([^{}]+)\}", r"\\end{\1}", data)

        data, num_thms, appx_thms, thm_scan = locate_theorems(data)

        num_thms = label_theorems(num_thms, thm_scan, False, data)

        appx_thms = label_theorems(appx_thms, thm_scan, True, data)

        return bundle_theorems(thm_scan, data, num_thms, appx_thms)


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
        json.dump(data, f, indent=4)