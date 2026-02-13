import re
from typing import Tuple

LABEL_RE = re.compile(r"""\\label\s*\{\s*([^{}]+?)\s*\}""")

def separate_body_and_label(body_and_label: str) -> Tuple[str, str | None]:
    """
    Separates body and label.

    Parameters
    ----------
    body_and_label : str
        Body and label together

    Returns
    -------
    body : str
        Body only
    label : str | None
        Label only if available
    """

    label_match = LABEL_RE.search(body_and_label)
    label = label_match.group(1).strip() if label_match else None

    if not label:
        label = None
    
    body = LABEL_RE.sub("", body_and_label, 1).strip()

    return body, label