from typing import TypedDict, Optional

class Theorem(TypedDict):
    """
    A Dict representation of a theorem-like environment extracted from a LaTeX source.

    Fields
    ------
        type : str
            The theorem environment type
        ref : str, optional
            The rendered theorem number as it appears in the document if available
        note : str, optional
            The optional theorem title or descriptor provided by the author if available
        label : str, optional
            The LaTeX label associated with the environment if available
        body:
            The LaTeX body of the environment. While not guaranteed to be expanded or sanitized,
            macros are expanded with a best-efforts approach
    """

    type: str
    ref: Optional[str]
    note: Optional[str]
    label: Optional[str]
    body: str