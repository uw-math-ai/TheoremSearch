"""
Scrape https://leanprover-community.github.io/lean_projects.html, find every
project whose GitHub repo contains a Lean blueprint, and register each one
under source = "Lean Community".

For each project:
  1. Resolve the GitHub slug (owner/repo) from the card.
  2. Shallow-clone the repo (no blob download) and look for a blueprint LaTeX
     source directory in a small list of common locations.
  3. If found:
       - title       = the project title shown on lean_projects.html
       - authors     = unique committer names on the blueprint source dir (git log)
       - url         = best-effort blueprint PDF URL (README link first,
                       project homepage's "blueprint"/"paper" button second,
                       <owner>.github.io/<repo>/blueprint.pdf third, repo URL last)
       - external_id = "<owner>/<repo>"
     Call add_paper(...) and upsert ``lean_community_paper_metadata``.

No GitHub API calls — everything goes through ``git`` (which uses the unauth'd
git smart-HTTP protocol, not rate limited like the REST API) and plain web
fetches. Set GITHUB_TOKEN to nothing — none required.
"""

import re
import shutil
import subprocess
import sys
import tempfile
from argparse import ArgumentParser
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

import requests
from tqdm import tqdm

from rds.utils.connect import get_rds_connection
from rds.utils.upsert import upsert_row
from ..add_paper.__main__ import add_paper
from ..printing import print_script_header


SOURCE = "Lean Community"
PROJECTS_URL = "https://leanprover-community.github.io/lean_projects.html"
USER_AGENT = "TheoremSearch-scraper/0.1 (+https://github.com/uw-math-ai)"

# Ordered by likelihood / preference. First hit wins.
BLUEPRINT_PATH_CANDIDATES = (
    "blueprint/src",
    "docs/blueprint/src",
    "blueprint",
)

README_NAMES = ("README.md", "README.rst", "README.txt", "README")
HTTP_TIMEOUT = 15


# ---------------------------------------------------------------------------
# lean_projects.html parser
# ---------------------------------------------------------------------------

GITHUB_SLUG_RE = re.compile(r"^https?://github\.com/([^/]+)/([^/#?]+)/?$")


class _ProjectsParser(HTMLParser):
    """
    Walks the lean_projects.html DOM and emits one (title, repo_url) pair per
    <h5> block. The page lists each project as:

        <h5>Project Name</h5>
        <p>... description, with a "View on GitHub" <a href="..."> link ...</p>

    We grab the title from the next text node inside <h5>, then take the first
    https://github.com/owner/repo URL that appears before the next <h5>.
    """

    def __init__(self):
        super().__init__()
        self.projects: list[tuple[str, str]] = []
        self._in_h5 = False
        self._current_title: list[str] = []
        self._pending_title: Optional[str] = None
        self._pending_repo: Optional[str] = None

    def _flush(self):
        if self._pending_title and self._pending_repo:
            self.projects.append((self._pending_title.strip(), self._pending_repo))
        self._pending_title = None
        self._pending_repo = None

    def handle_starttag(self, tag, attrs):
        if tag == "h5":
            self._flush()
            self._in_h5 = True
            self._current_title = []
        elif tag == "a" and self._pending_title and not self._pending_repo:
            href = dict(attrs).get("href", "")
            if GITHUB_SLUG_RE.match(href):
                self._pending_repo = href

    def handle_endtag(self, tag):
        if tag == "h5" and self._in_h5:
            self._in_h5 = False
            self._pending_title = "".join(self._current_title).strip()
            self._current_title = []

    def handle_data(self, data):
        if self._in_h5:
            self._current_title.append(data)

    def close(self):
        self._flush()
        super().close()


def fetch_projects() -> list[tuple[str, str]]:
    """Return [(title, repo_url), ...] from the Lean Community projects page."""
    resp = requests.get(PROJECTS_URL, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    parser = _ProjectsParser()
    parser.feed(resp.text)
    parser.close()
    return parser.projects


def parse_slug(repo_url: str) -> Optional[str]:
    m = GITHUB_SLUG_RE.match(repo_url)
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    return f"{owner}/{repo}"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _run_git(args: list[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def shallow_clone(slug: str, dest: Path) -> None:
    # --filter=blob:none gives us full history + tree metadata, lazy-fetching
    # blobs only when we actually read a file. Cheap for our use.
    _run_git([
        "clone", "--quiet", "--filter=blob:none", "--no-checkout",
        f"https://github.com/{slug}.git", str(dest),
    ])


def default_branch(repo_dir: Path) -> str:
    """Return the default branch name (e.g. "main", "master")."""
    try:
        res = _run_git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=repo_dir)
        return res.stdout.strip().removeprefix("origin/")
    except subprocess.CalledProcessError:
        # Fall back to whatever HEAD points at.
        res = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir)
        return res.stdout.strip()


def list_tree(repo_dir: Path, branch: str) -> list[str]:
    """Recursive file listing for the given branch (no blob fetch needed)."""
    res = _run_git(["ls-tree", "-r", "--name-only", branch], cwd=repo_dir)
    return res.stdout.splitlines()


def find_blueprint_src(repo_dir: Path, branch: str) -> Optional[str]:
    """
    Return the path (relative to repo root) of the first candidate directory
    that exists in this branch and contains at least one .tex file. None if
    no blueprint source can be located.
    """
    files = list_tree(repo_dir, branch)
    by_dir: dict[str, list[str]] = {}
    for f in files:
        d, _, _ = f.rpartition("/")
        by_dir.setdefault(d, []).append(f)

    def has_tex_under(prefix: str) -> bool:
        prefix_slash = prefix + "/" if prefix else ""
        return any(
            f.startswith(prefix_slash) and f.endswith(".tex")
            for f in files
        )

    for candidate in BLUEPRINT_PATH_CANDIDATES:
        if candidate in by_dir or any(d.startswith(candidate + "/") for d in by_dir):
            if has_tex_under(candidate):
                return candidate
    return None


def _name_score(name: str) -> tuple:
    """Higher score = looks more like a real name. Used to pick a display
    name when one author has committed under several aliases (e.g. their
    real name in some commits and a GitHub username in others)."""
    # Prefer multi-word names (likely real names) over single-token (likely
    # usernames); among same-class names, prefer longer.
    return (1 if " " in name else 0, len(name))


def authors_for_path(repo_dir: Path, path: str) -> list[str]:
    """
    One display name per committer who has touched ``path`` (or anything
    under it). Grouped by author email so the same person committing under
    multiple ``user.name`` values folds into a single entry, and the best
    candidate (typically the real-name version, not the GitHub login) wins.
    Returned in first-seen email order.
    """
    res = _run_git(
        ["log", "--format=%ae%x09%aN", "--", path],
        cwd=repo_dir,
        check=False,
    )
    best_name_by_email: dict[str, str] = {}
    email_order: list[str] = []
    for line in res.stdout.splitlines():
        email, _, name = line.partition("\t")
        email = email.strip().lower()
        name = name.strip()
        if not email or not name:
            continue
        if email not in best_name_by_email:
            best_name_by_email[email] = name
            email_order.append(email)
        elif _name_score(name) > _name_score(best_name_by_email[email]):
            best_name_by_email[email] = name
    return [best_name_by_email[e] for e in email_order]


def read_file_at_branch(repo_dir: Path, branch: str, path: str) -> Optional[str]:
    """Read a single file's content from the given branch (forces blob fetch)."""
    res = _run_git(["show", f"{branch}:{path}"], cwd=repo_dir, check=False)
    if res.returncode != 0:
        return None
    return res.stdout


def find_readme(repo_dir: Path, branch: str, files: list[str]) -> Optional[str]:
    top_level = {f for f in files if "/" not in f}
    for name in README_NAMES:
        if name in top_level:
            return read_file_at_branch(repo_dir, branch, name)
    # Some repos use lowercase or odd casing.
    for f in top_level:
        if f.lower().startswith("readme"):
            return read_file_at_branch(repo_dir, branch, f)
    return None


# ---------------------------------------------------------------------------
# PDF URL discovery
# ---------------------------------------------------------------------------

MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
HTML_HREF_RE = re.compile(r'<a[^>]+href=["\'](https?://[^"\']+)["\'][^>]*>([^<]{0,200})</a>', re.IGNORECASE)


def _looks_like_blueprint_link(label: str, href: str) -> bool:
    text = (label + " " + href).lower()
    if not href.lower().endswith(".pdf"):
        return False
    return "blueprint" in text or "paper" in text


def pdf_from_text(text: str) -> Optional[str]:
    """
    Look through markdown- or HTML-style links in ``text`` and return the
    first one that looks like a blueprint/paper PDF.
    """
    for label, href in MD_LINK_RE.findall(text):
        if _looks_like_blueprint_link(label, href):
            return href
    for href, label in HTML_HREF_RE.findall(text):
        if _looks_like_blueprint_link(label, href):
            return href
    return None


def homepage_from_readme(text: str, slug: str) -> Optional[str]:
    """
    Heuristic: pick the first http(s) link in the README that isn't pointing
    back at the repo itself or another GitHub page. Lean Community projects
    usually link their hosted blueprint site near the top.
    """
    owner, repo = slug.split("/", 1)
    self_hosts = (
        "github.com",
    )
    for _label, href in MD_LINK_RE.findall(text):
        host = urlparse(href).netloc.lower()
        if not host:
            continue
        if any(host == h or host.endswith("." + h) for h in self_hosts):
            continue
        return href
    for href, _label in HTML_HREF_RE.findall(text):
        host = urlparse(href).netloc.lower()
        if not host:
            continue
        if any(host == h or host.endswith("." + h) for h in self_hosts):
            continue
        return href
    return None


def head_ok(url: str) -> bool:
    try:
        r = requests.head(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=HTTP_TIMEOUT,
            allow_redirects=True,
        )
        return r.status_code < 400
    except requests.RequestException:
        return False


def discover_pdf_url(slug: str, repo_dir: Path, branch: str, files: list[str]) -> str:
    repo_url = f"https://github.com/{slug}"
    readme = find_readme(repo_dir, branch, files)

    if readme:
        pdf = pdf_from_text(readme)
        if pdf:
            return pdf

        homepage = homepage_from_readme(readme, slug)
        if homepage:
            try:
                r = requests.get(
                    homepage,
                    headers={"User-Agent": USER_AGENT},
                    timeout=HTTP_TIMEOUT,
                )
                if r.ok:
                    pdf = pdf_from_text(r.text)
                    if pdf:
                        # Resolve in case the page used a relative href.
                        return urljoin(homepage, pdf)
            except requests.RequestException:
                pass

    owner, repo = slug.split("/", 1)
    convention = f"https://{owner}.github.io/{repo}/blueprint.pdf"
    if head_ok(convention):
        return convention

    return repo_url


# ---------------------------------------------------------------------------
# Per-project processing
# ---------------------------------------------------------------------------

def already_registered(conn, slug: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM paper WHERE source = %s AND external_id = %s",
            (SOURCE, slug),
        )
        return cur.fetchone() is not None


def process_project(title: str, repo_url: str, overwrite: bool) -> tuple[str, str]:
    """
    Returns (status, message). status ∈ {"added", "skipped", "no-blueprint", "error"}.
    """
    slug = parse_slug(repo_url)
    if not slug:
        return ("error", f"could not parse slug from {repo_url}")

    conn = get_rds_connection("v2")
    if not overwrite and already_registered(conn, slug):
        return ("skipped", f"{slug} already registered")

    with tempfile.TemporaryDirectory(prefix="lean-community-") as tmp:
        repo_dir = Path(tmp) / "repo"
        try:
            shallow_clone(slug, repo_dir)
        except subprocess.CalledProcessError as e:
            return ("error", f"clone failed for {slug}: {e.stderr.strip() or e}")

        branch = default_branch(repo_dir)
        files = list_tree(repo_dir, branch)
        src_path = find_blueprint_src(repo_dir, branch)
        if src_path is None:
            return ("no-blueprint", f"{slug}: no blueprint source dir found")

        authors = authors_for_path(repo_dir, src_path)
        url = discover_pdf_url(slug, repo_dir, branch, files)

    add_paper(
        kind="blueprint",
        source=SOURCE,
        external_id=slug,
        title=title,
        authors=authors,
        url=url,
        overwrite=overwrite,
    )

    # Refresh the connection — add_paper committed and closed its own cursor
    # but the connection object is shared via the cached pool helper.
    conn = get_rds_connection("v2")
    upsert_row(
        conn,
        table="lean_community_paper_metadata",
        row={
            "repo_slug": slug,
            "branch": branch,
            "src_path": src_path,
        },
        on_conflict={
            "with": ["repo_slug"],
            "replace": ["branch", "src_path"],
        },
    )
    conn.commit()

    return ("added", f"{slug} ← {src_path} (branch {branch}, {len(authors)} authors)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def scrape_lean_community(overwrite: bool, limit: Optional[int], match: Optional[str]) -> None:
    print_script_header(
        action="Scraping Lean Community blueprints",
        params={
            "source page": PROJECTS_URL,
            "overwrite": overwrite,
            "limit?": limit,
            "match?": match,
        },
    )

    projects = fetch_projects()
    print(f"Found {len(projects)} project cards.")
    if match:
        pattern = re.compile(match, re.IGNORECASE)
        projects = [(t, u) for t, u in projects if pattern.search(t) or pattern.search(u)]
        print(f"  {len(projects)} match --match={match!r}.")
    if limit is not None:
        projects = projects[:limit]
        print(f"  limited to first {len(projects)}.")

    counts = {"added": 0, "skipped": 0, "no-blueprint": 0, "error": 0}
    pbar = tqdm(projects, dynamic_ncols=True)
    for title, repo_url in pbar:
        pbar.set_description(title[:40])
        try:
            status, msg = process_project(title, repo_url, overwrite)
        except Exception as e:
            status, msg = ("error", f"unhandled: {e}")
        counts[status] += 1
        pbar.write(f"{status}: {msg}")
        pbar.set_postfix(added=counts["added"], **{k: counts[k] for k in ("skipped", "no-blueprint", "error") if counts[k]})

    print("\nSummary:")
    for k, v in counts.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        description='Scrape Lean Community blueprints and register them under source="Lean Community".'
    )
    arg_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-register projects that already exist (source='Lean Community').",
    )
    arg_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most this many projects (after --match). Useful for smoke tests.",
    )
    arg_parser.add_argument(
        "--match",
        type=str,
        default=None,
        help="Case-insensitive regex; only projects whose title or repo URL matches are processed.",
    )
    args = arg_parser.parse_args()

    sys.exit(scrape_lean_community(
        overwrite=args.overwrite,
        limit=args.limit,
        match=args.match,
    ))
