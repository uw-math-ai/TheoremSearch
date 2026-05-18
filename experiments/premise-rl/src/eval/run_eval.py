"""Main evaluation entry point.

Usage:
    python -m src.eval.run_eval --config configs/smoke_test.yaml

Runs GPT policy over the 100 theorems in rl_test_100, writes:
    <results_dir>/trajectories.jsonl   — one JSON object per episode
    <results_dir>/summary.json         — aggregate statistics
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv
from openai import AsyncOpenAI

from src._config import Config
from src.data.id_mapping import IDMapper
from src.data.load_targets import load_all_data, print_checkpoint_stats
from src.env.environment import PremiseSelectionEnv
from src.env.search_client import TheoremSearchClient
from src.eval.metrics import compute_summary
from src.policies.gpt54_prompted import run_episode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


async def _run_all(config: Config, system_prompt: str) -> list[dict]:
    logger.info("Loading target data (cache: %s) …", config.data_cache_path)
    targets, dep_stmts = load_all_data(cache_path=config.data_cache_path)
    print_checkpoint_stats(targets, dep_stmts)

    logger.info("Building ID mapper over %d dep statements …", len(dep_stmts))
    id_mapper = IDMapper(dep_stmts, config.match_threshold, config.low_confidence_gap)

    search_client = TheoremSearchClient(cache_dir=config.cache_dir)
    openai_client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

    sem = asyncio.Semaphore(config.concurrency)
    target_ids = list(targets.keys())
    logger.info("Running %d episodes (concurrency=%d) …", len(target_ids), config.concurrency)

    async def _episode(tid: UUID) -> dict:
        async with sem:
            env = PremiseSelectionEnv(targets, search_client, id_mapper, config)
            return await run_episode(env, tid, openai_client, config, system_prompt)

    results = await asyncio.gather(*(_episode(tid) for tid in target_ids))

    await search_client.close()
    await openai_client.close()

    return list(results)


def _write_outputs(results: list[dict], config: Config) -> None:
    out_dir = Path(config.results_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    traj_path = out_dir / "trajectories.jsonl"
    with traj_path.open("w", encoding="utf-8") as f:
        for ep in results:
            f.write(json.dumps(ep, ensure_ascii=False) + "\n")
    logger.info("Trajectories written to %s", traj_path)

    summary = compute_summary(results, {})
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    logger.info("Summary written to %s", summary_path)

    print("\n── Summary ──────────────────────────────────────────")
    print(f"  mean_recall:            {summary['mean_recall']:.3f}")
    print(f"  recall_by_bucket:       {summary['recall_by_dep_bucket']}")
    print(f"  mean_queries/ep:        {summary['mean_queries_per_episode']:.2f}")
    print(f"  unique_query_rate:      {summary['unique_query_rate']:.3f}")
    print(f"  mean_fp/ep:             {summary['mean_fp_per_episode']:.2f}")
    print(f"  dropped_no_match_rate:  {summary['dropped_no_match_rate']:.3f}")
    print(f"  low_conf_match_rate:    {summary['low_confidence_match_rate']:.3f}")
    if summary.get("low_confidence_match_rate", 0) > 0.05:
        print("  WARNING: low_confidence_match_rate > 5% — inspect sample of low-conf matches")
    print("─────────────────────────────────────────────────────")


def main() -> None:
    load_dotenv()

    ap = argparse.ArgumentParser(description="Premise-selection smoke-test evaluation")
    ap.add_argument("--config", required=True, help="Path to YAML config file")
    args = ap.parse_args()

    config = Config.from_yaml(args.config)
    logger.info("Config loaded from %s", args.config)
    logger.info("Model: %s  H=%d  k=%d  concurrency=%d", config.model, config.H, config.k, config.concurrency)

    prompt_path = Path(config.system_prompt_path)
    if not prompt_path.exists():
        raise FileNotFoundError(f"System prompt not found: {prompt_path}")
    system_prompt = prompt_path.read_text(encoding="utf-8")

    results = asyncio.run(_run_all(config, system_prompt))
    _write_outputs(results, config)


if __name__ == "__main__":
    main()
