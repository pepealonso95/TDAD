"""SWE-bench Verified dataset loader."""

import json
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"


def load_instances(
    dataset: str = "princeton-nlp/SWE-bench_Verified",
    limit: Optional[int] = None,
    instance_ids: Optional[List[str]] = None,
) -> List[dict]:
    """Load SWE-bench instances, preferring a local cache.

    Each returned dict has at least:
      instance_id, repo, base_commit, problem_statement,
      FAIL_TO_PASS, PASS_TO_PASS
    """
    # Try local cache first
    cache_file = DATA_DIR / f"{dataset.replace('/', '__')}.json"
    if cache_file.exists():
        logger.info("Loading instances from cache: %s", cache_file)
        with open(cache_file) as f:
            instances = json.load(f)
    else:
        logger.info("Loading instances from HuggingFace: %s", dataset)
        try:
            from datasets import load_dataset
        except ImportError:
            raise RuntimeError(
                "Install the 'datasets' package: pip install datasets"
            )

        ds = load_dataset(dataset, split="test")
        instances = [dict(row) for row in ds]

        # Cache for next time
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump(instances, f)
        logger.info("Cached %d instances to %s", len(instances), cache_file)

    # Filter by specific IDs if requested
    if instance_ids:
        id_set = set(instance_ids)
        instances = [i for i in instances if i["instance_id"] in id_set]
        missing = id_set - {i["instance_id"] for i in instances}
        if missing:
            logger.warning("Instance IDs not found in dataset: %s", missing)

    # Apply limit
    if limit is not None:
        instances = instances[:limit]

    logger.info("Loaded %d instances", len(instances))
    return instances
