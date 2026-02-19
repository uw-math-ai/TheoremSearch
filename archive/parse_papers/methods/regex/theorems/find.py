from typing import Dict, List
from ....types import Theorem
from .find_proclaims import find_proclaims
from .find_envs import find_envs
from .find_bf_it_blocks import find_bf_it_blocks

def find_theorems(tex: str, theorem_envs: Dict[str, str]) -> List[Theorem]:
    theorems: List[Theorem] = []
    main_theorem_types = list(set(theorem_envs.values()))

    theorems.extend(find_proclaims(tex, main_theorem_types))
    theorems.extend(find_bf_it_blocks(tex, main_theorem_types))
    theorems.extend(find_envs(tex, theorem_envs))

    return theorems