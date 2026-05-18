"""
Lean Community source. Materializes a paper's blueprint LaTeX by shallow-
cloning the GitHub repo at parse time, using ``(branch, src_path)`` looked up
from ``lean_community_paper_metadata``.
"""

import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List

from psycopg2.extras import Json

from rds.utils.upsert import update_rows
from .base import ParseAttempt, Source


class LeanCommunitySource(Source):
    name = "Lean Community"

    def prefetch_metadata(self, conn, external_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        if not external_ids:
            return {}
        with conn.cursor() as cur:
            cur.execute(
                "SELECT repo_slug, branch, src_path "
                "FROM lean_community_paper_metadata "
                "WHERE repo_slug = ANY(%s)",
                (external_ids,),
            )
            rows = cur.fetchall()
        return {
            slug: {"branch": branch, "src_path": src_path}
            for slug, branch, src_path in rows
        }

    @contextmanager
    def materialize(self, external_id: str, prefetched: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        if "branch" not in prefetched or "src_path" not in prefetched:
            raise RuntimeError(
                f"missing lean_community_paper_metadata for {external_id}"
            )
        branch = prefetched["branch"]
        src_path = prefetched["src_path"]
        with tempfile.TemporaryDirectory(prefix="lean-community-parse-") as tmp:
            repo_dir = Path(tmp) / "repo"
            subprocess.run(
                [
                    "git", "clone", "--quiet",
                    "--depth", "1",
                    "--branch", branch,
                    "--filter=blob:none",
                    "--no-checkout",
                    f"https://github.com/{external_id}.git",
                    str(repo_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            # Only fetch the blueprint source subtree.
            subprocess.run(
                ["git", "sparse-checkout", "set", "--no-cone", src_path],
                cwd=repo_dir, check=True, capture_output=True, text=True,
            )
            subprocess.run(
                ["git", "checkout", branch, "--", src_path],
                cwd=repo_dir, check=True, capture_output=True, text=True,
            )

            paper_dir = repo_dir / src_path
            if not paper_dir.is_dir():
                raise RuntimeError(
                    f"{external_id}: expected source at {src_path} not found after checkout"
                )

            yield {"paper_path": paper_dir}

    def preamble_done_sql(self) -> str:
        return """
            paper.source = 'Lean Community' AND EXISTS (
                SELECT 1 FROM lean_community_paper_metadata
                WHERE repo_slug = paper.external_id AND preamble IS NOT NULL
            )
        """

    def bibliography_done_sql(self) -> str:
        return """
            paper.source = 'Lean Community' AND EXISTS (
                SELECT 1 FROM lean_community_paper_metadata
                WHERE repo_slug = paper.external_id AND bibliography IS NOT NULL
            )
        """

    def record_attempt(self, attempt: ParseAttempt, batch: Dict[str, list]) -> None:
        if attempt.preamble is not None:
            batch.setdefault("preamble", []).append({
                "repo_slug": attempt.external_id,
                "preamble": attempt.preamble,
            })
        if attempt.bibliography:
            batch.setdefault("bibliography", []).append({
                "repo_slug": attempt.external_id,
                "bibliography": Json(attempt.bibliography),
                "bibtex": attempt.bibliography_bibtex,
            })

    def commit_batch(self, conn, batch: Dict[str, list]) -> None:
        if batch.get("preamble"):
            update_rows(
                conn,
                table="lean_community_paper_metadata",
                rows=batch["preamble"],
                where=["repo_slug"],
            )
        if batch.get("bibliography"):
            update_rows(
                conn,
                table="lean_community_paper_metadata",
                rows=batch["bibliography"],
                where=["repo_slug"],
                casts={"bibliography": "jsonb"},
            )
