from plasTeX.DOM import Node
import re
from typing import Tuple

LABEL_RE = re.compile(r"""\\label\s*\{\s*([^{}]+?)\s*\}""")

def _strip_nuls(x):
    if isinstance(x, str):
        return x.replace("\x00", "")
    if isinstance(x, (bytes, bytearray, memoryview)):
        return bytes(x).replace(b"\x00", b"").decode("utf-8", errors="replace")
    return x

def _get_node_body_and_label(node: Node) -> Tuple[str, str | None]:
    body_and_label = ""

    for child in getattr(node, "childNodes", []):
        tex_src = getattr(
            child, "source", 
            getattr(child, "textContent", "")
        )

        body_and_label += tex_src.strip()

    label_match = LABEL_RE.search(body_and_label)
    label = label_match.group(1).strip() if label_match else None

    if not label:
        label = None
    else:
        label = _strip_nuls(label)

    body = _strip_nuls(LABEL_RE.sub("", body_and_label)).strip()

    return body, label

def _get_node_ref(node: Node) -> str | None:
    return _strip_nuls(getattr(node.ref, "source", None) if hasattr(node, "ref") else None)

def _get_node_note(node: Node) -> str | None:
    if hasattr(node, "title"):
        return _strip_nuls(getattr(node.title, "source", None))

    return None

def parse_node(node: Node) -> Tuple[str | None, str | None, str | None, str]:
    """
    Parses a Node for a Theorem.

    Parameters
    ----------
    node: Node
        PlasTeX node to parse
    
    Returns
    -------
    ref: str, optional
    note: str, optional
    label: str, optional
    body: str
    """

    body, label = _get_node_body_and_label(node)

    return (
        _get_node_ref(node),
        _get_node_note(node),
        label, body
    )