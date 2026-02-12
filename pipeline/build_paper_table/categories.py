"""
arXiv categories that likely contain mathematical theorems
"""

from typing import List

_CS_CATEGORIES: List[str] = [
    "cs." + cat for cat in
    "AI,CC,CE,CG,CR,DM,FL,GT,IT,LG,LO,NA,SC".split(",")
]

_PHYS_CATEGORIES: List[str] = [
    "astro-ph.IM",
    *("cond-mat." + cat for cat in "dis-nn,stat-mech".split(",")),
    "hep-th",
    "math-ph",
    "nlin",
    "physics",
    "quant-ph"
]

_QFIN_CATEGORIES: List[str] = [
    "q-fin." + cat for cat in
    "CP,EC,MF,PR,RM,ST".split(",")
]

CATEGORIES: List[str] = [
    *_CS_CATEGORIES,
    "econ"
    "eess",
    "math",
    *_PHYS_CATEGORIES,
    "q-bio.QM",
    *_QFIN_CATEGORIES,
    "stat"
]