import arxiv
import time
import random
from typing import Iterable, List, Optional, Set
import random

def search_arxiv(
    query: str,
    page_size: int = 8,
    *,
    delay_seconds: float = 0.4,
    jitter: float = 0.15,
    sort_by: arxiv.SortCriterion = arxiv.SortCriterion.LastUpdatedDate,
    num_retries: int = 3,
    max_results: Optional[int] = None
) -> Iterable[List[arxiv.Result]]:
    client = arxiv.Client(
        page_size=random.randint(64, 128),
        delay_seconds=delay_seconds,
        num_retries=num_retries,
    )

    def _sleep():
        if delay_seconds:
            time.sleep(max(0.0, delay_seconds * (1.0 + random.uniform(-jitter, jitter))))

    buf: List[arxiv.Result] = []
    seen: Set[str] = set()

    search = arxiv.Search(
        query=query,
        sort_by=sort_by,
        max_results=max_results,
    )

    try:
        while True:
            try:
                for res in client.results(search):
                    _sleep()
                    sid = res.get_short_id()
                    if sid in seen:
                        continue
                    seen.add(sid)
                    buf.append(res)
                    if len(buf) == page_size:
                        yield buf
                        buf = []
                break

            except arxiv.UnexpectedEmptyPageError:
                client.page_size = random.randint(64, 128)
                time.sleep(1.5)
                continue 

        if buf:
            yield buf

    except KeyboardInterrupt:
        if buf:
            yield buf
        raise