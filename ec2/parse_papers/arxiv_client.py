import arxiv
import time
import random
from typing import Iterable, List, Optional, Set

def search_arxiv(
    query: str,
    page_size: int = 8,
    *,
    delay_seconds: float = 0.4,
    jitter: float = 0.15,
    sort_by: arxiv.SortCriterion = arxiv.SortCriterion.SubmittedDate,
    num_retries: int = 3,
    max_results: Optional[int] = None
) -> Iterable[List[arxiv.Result]]:
    client = arxiv.Client(
        page_size=100,
        delay_seconds=delay_seconds,
        num_retries=num_retries,
    )

    search = arxiv.Search(
        query=query,
        sort_by=sort_by,
        max_results=max_results,
    )

    buf: List[arxiv.Result] = []
    seen: Set[str] = set()
    key = (lambda r: r.get_short_id())
    yielded = 0

    try:
        for res in client.results(search):
            if delay_seconds:
                time.sleep(max(0.0, delay_seconds * (1.0 + random.uniform(-jitter, jitter))))

            k = key(res)
            if k in seen:
                continue
            seen.add(k)

            buf.append(res)

            if len(buf) == page_size:
                yield buf
                yielded += len(buf)
                buf = []

        if buf:
            yield buf

    except KeyboardInterrupt:
        if buf:
            yield buf
        raise