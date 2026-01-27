"""
arXiv categories that likely contain mathematical theorems
"""

from typing import List

MATH_CATEGORIES: List[str] = [
    "math." + cat for cat in
    "AC,AG,AP,AT,CA,CO,CT,CV,DG,DS,FA,GM,GN,GR,GT,IT,KT,LO,MG,MP,NA,NT,OA,OC,PR,QA,RA,RT,SG,SP,ST".split(",")
]

STAT_CATEGORIES: List[str] = [
    "stat." + cat for cat in
    "AP,CO,ME,ML,OT,TH".split(",")
]

CS_CATEGORIES: List[str] = [
    "cs." + cat for cat in
    "AI,CC,CE,CG,CR,DM,GT,IT,LG,LO,NA,SC".split(",")
]

MATH_PHYS_CATEGORIES: List[str] = ["math-ph"]

PHYS_CATEGORIES: List[str] = [
    "physics." + cat for cat in
    "class-ph,comp-ph,data-an,flu-dyn,gen-ph".split(",")
]

CATEGORIES: List[str] = [
    *MATH_CATEGORIES,
    *STAT_CATEGORIES,
    *CS_CATEGORIES,
    *MATH_PHYS_CATEGORIES,
    *PHYS_CATEGORIES
]