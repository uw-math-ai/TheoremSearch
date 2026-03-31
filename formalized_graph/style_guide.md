# LeanDojo Python Style Guide

This guide captures the coding conventions and architectural patterns used in the LeanDojo-v2 repository. We should adhere to these standards when building our "Ground Truth" ingestion engine.

## 1. Core Header & Imports
Always enable postponed evaluation of annotations for modern type hinting. Imports are grouped: Standard Library, Third-Party, then Local.

```python
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from loguru import logger
from tqdm import tqdm

from lean_dojo_v2.utils.common import execute
```

## 2. Data Modeling (Dataclasses)
Use `dataclasses` for structured data. Use `field(init=False)` for properties calculated in `__post_init__`.

```python
@dataclass(frozen=True)
class LeanFile:
    """A Lean source file (*.lean)."""

    root_dir: Path = field(repr=False)
    """Root directory of the traced repo."""

    path: Path
    """Relative path w.r.t. root_dir."""

    code: List[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # Validation and post-initialization logic
        assert self.path.suffix == ".lean", f"Invalid extension: {self.path}"
        # Use object.__setattr__ for frozen dataclasses
        object.__setattr__(self, "code", self.abs_path.read_text().splitlines())
```

## 3. Function Signatures & Docstrings
Use Google-style docstrings. Parameters should always be type-hinted.

```python
def trace(
    repo: LeanGitRepo,
    dst_dir: Optional[Union[str, Path]] = None,
    build_deps: bool = False,
) -> TracedRepo:
    """Trace a repo (and its dependencies), saving the results to dst_dir.

    The function only traces the repo when it's not available in the cache.

    Args:
        repo (LeanGitRepo): The Lean repo to trace.
        dst_dir (Union[str, Path]): The directory for saving the traced repo.
        build_deps (bool): Whether to build the dependencies.

    Returns:
        TracedRepo: A TracedRepo object corresponding to the files.
    """
    if dst_dir is not None:
        dst_dir = Path(dst_dir)
        assert not dst_dir.exists(), f"Directory {dst_dir} already exists."
```

## 4. Error Handling & Logging
Prefer `loguru` for context-rich logging. Use `assert` for internal consistency checks and `logger.error` for runtime failures.

```python
logger.debug(f"Tracing {repo}")
try:
    execute("lake build")
except CalledProcessError as ex:
    logger.warning(f"Build failed for {repo.name}: {ex}")
```

## 5. Filesystem & Working Directory
Use `contextmanager` for operations that change state, like switching directories.

```python
@contextmanager
def working_directory(path: Path) -> Generator[None, None, None]:
    prev_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev_cwd)
```

## 6. Formatting & Indentation
- **Indentation**: Strict 4-space indent.
- **Line Length**: Targets ~88-100 characters.
- **Naming**: `CamelCase` for classes, `snake_case` for functions/variables, `_private_names` for internal helpers.

## Attribution & Credits

Heavily derived from and inspired by the **[LeanDojo](https://github.com/leanprover-community/LeanDojo)** project.

**LeanDojo Citation:**
> Yang, K., Song, D., Kawasaki, Y., Selsam, D., Gu, G., & Chi, J. (2023). **LeanDojo: Theorem Proving with Retrieval-Augmented Language Models.** *NeurIPS 2023*.