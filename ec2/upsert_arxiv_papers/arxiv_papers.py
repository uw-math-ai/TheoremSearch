import arxiv
from datetime import datetime, timedelta
from typing import Iterator, Literal, Tuple

DatePartition = Literal["year", "month", "week", "day"]

def _format_dt(dt: datetime):
    return dt.strftime("%Y%m%d%H%M%S")

def _get_date_partitions(
    date_partition: DatePartition,
    start_date: datetime,
    end_date: datetime
) -> Iterator[Tuple[str, str]]:
    curr_date = start_date
    next_date = None

    while curr_date < end_date:
        if date_partition == "year":
            next_date = datetime(curr_date.year + 1, 1, 1)

        elif date_partition == "month":
            if curr_date.month == 12:
                next_date = datetime(curr_date.year + 1, 1, 1)
            else:
                next_date = datetime(curr_date.year, curr_date.month + 1, 1)

        elif date_partition == "week":
            next_date = curr_date + timedelta(days=7)

        elif date_partition == "day":
            next_date = curr_date + timedelta(days=1)

        else:
            raise ValueError(f"Unsupported partition: {partition}")

        yield _format_dt(curr_date), _format_dt(next_date)

        curr_date = next_date

def get_arxiv_papers(
    client: arxiv.Client, 
    query: str, 
    date_partition: DatePartition,
    start_date: datetime = datetime(1992, 1, 1),
    end_date: datetime = datetime.now()
) -> Iterator[arxiv.Result]:
    for start, end in _get_date_partitions(date_partition, start_date, end_date):
        search = arxiv.Search(
            query=f"submittedDate:[{start} TO {end}] AND {query}"
        )

        for paper_res in client.results(search):
            yield paper_res
        