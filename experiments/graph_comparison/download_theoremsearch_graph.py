#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://api.theoremsearch.com/graph"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_TOKEN_ENV = "THEOREMSEARCH_API_TOKEN"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download a theorem dependency graph JSON payload from the "
            "TheoremSearch API."
        )
    )
    parser.add_argument(
        "external_id",
        help="Paper external_id, for example 2507.08642 or math/0404392.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Optional output path. Defaults to "
            "<external_id>_API.json in the current directory."
        ),
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"API endpoint base URL. Defaults to {DEFAULT_BASE_URL}.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Request timeout in seconds. Defaults to {DEFAULT_TIMEOUT_SECONDS}.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting an existing output file.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Write compact JSON instead of pretty-printed JSON.",
    )
    parser.add_argument(
        "--token-env",
        default=DEFAULT_TOKEN_ENV,
        help=(
            "Optional environment-variable name holding a bearer token. "
            f"Defaults to {DEFAULT_TOKEN_ENV}."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = args.output or default_output_path(args.external_id)

    if output_path.exists() and not args.overwrite:
        print(
            f"Refusing to overwrite existing file: {output_path}. "
            "Pass --overwrite to replace it.",
            file=sys.stderr,
        )
        return 1

    request_url = build_request_url(args.base_url, args.external_id)
    token = read_token(args.token_env)

    try:
        payload = fetch_json(request_url, timeout=args.timeout, token=token)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(payload, output_path, compact=args.compact)

    paper = payload.get("paper") if isinstance(payload, dict) else None
    title = paper.get("title") if isinstance(paper, dict) else None
    statements = payload.get("statements") if isinstance(payload, dict) else None
    dependencies = payload.get("dependencies") if isinstance(payload, dict) else None

    print(f"Downloaded {request_url}")
    if title:
        print(f"Paper title: {title}")
    if isinstance(statements, list):
        print(f"Statements: {len(statements)}")
    if isinstance(dependencies, list):
        print(f"Dependencies: {len(dependencies)}")
    print(f"Wrote JSON to {output_path.resolve()}")
    return 0


def default_output_path(external_id: str) -> Path:
    safe_id = sanitize_filename(external_id)
    return Path(f"{safe_id}_API.json")


def sanitize_filename(value: str) -> str:
    cleaned = []
    for char in value.strip():
        if char.isalnum() or char in {".", "-", "_"}:
            cleaned.append(char)
        else:
            cleaned.append("_")
    return "".join(cleaned) or "theoremsearch_graph"


def build_request_url(base_url: str, external_id: str) -> str:
    encoded_id = urllib.parse.quote(external_id, safe="")
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}external_id={encoded_id}"


def read_token(token_env: str | None) -> str | None:
    if not token_env:
        return None
    token = os.environ.get(token_env)
    return token.strip() if token else None


def fetch_json(url: str, timeout: float, token: str | None) -> Any:
    headers = {
        "Accept": "application/json",
        "User-Agent": "theoremsearch-graph-downloader/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_body = response.read()
            status_code = getattr(response, "status", None)
            if status_code is not None and status_code >= 400:
                raise RuntimeError(f"API returned HTTP {status_code} for {url}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        if detail:
            raise RuntimeError(f"HTTP {exc.code} for {url}: {detail}") from exc
        raise RuntimeError(f"HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach {url}: {exc.reason}") from exc

    try:
        return json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Response from {url} was not valid JSON: {exc}") from exc


def write_json(payload: Any, output_path: Path, compact: bool) -> None:
    if compact:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        text += "\n"
    output_path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
