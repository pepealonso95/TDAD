#!/usr/bin/env python3
"""
Cache SWE-bench datasets locally for faster loading

Downloads and saves the dataset to a local directory so subsequent
loads don't require network access or slow HuggingFace cache lookups.
"""

import argparse
from pathlib import Path
from datasets import load_dataset
import json


def cache_dataset(dataset_name: str, cache_dir: str = "data"):
    """
    Download and cache SWE-bench dataset locally

    Args:
        dataset_name: HuggingFace dataset name (e.g., princeton-nlp/SWE-bench_Verified)
        cache_dir: Local directory to save dataset
    """
    cache_path = Path(cache_dir)
    cache_path.mkdir(exist_ok=True)

    print(f"Downloading dataset: {dataset_name}")
    print(f"This may take a few minutes on first run...")

    # Load dataset (will use HuggingFace cache if available)
    dataset = load_dataset(dataset_name, split='test')

    print(f"Dataset loaded: {len(dataset)} instances")

    # Save to local JSON file for faster subsequent access
    dataset_filename = dataset_name.replace("/", "_") + ".json"
    output_path = cache_path / dataset_filename

    print(f"Saving to: {output_path}")

    # Convert to list of dicts and save
    instances = []
    for item in dataset:
        instances.append(dict(item))

    with open(output_path, 'w') as f:
        json.dump(instances, f, indent=2)

    print(f"✅ Dataset cached successfully!")
    print(f"   - {len(instances)} instances")
    print(f"   - Saved to: {output_path}")
    print(f"   - Size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")

    # Create a quick access file with just instance IDs and test info
    quick_access_path = cache_path / dataset_filename.replace(".json", "_tests.json")
    test_info = {}
    for item in instances:
        test_info[item['instance_id']] = {
            'fail_to_pass': item.get('FAIL_TO_PASS', []),
            'pass_to_pass': item.get('PASS_TO_PASS', []),
            'repo': item.get('repo', ''),
            'base_commit': item.get('base_commit', '')
        }

    with open(quick_access_path, 'w') as f:
        json.dump(test_info, f, indent=2)

    print(f"✅ Quick access file created: {quick_access_path}")
    print(f"   - Use this for faster test info lookups")

    return output_path, quick_access_path


def main():
    parser = argparse.ArgumentParser(
        description="Cache SWE-bench dataset locally"
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="princeton-nlp/SWE-bench_Verified",
        help="Dataset name to cache (default: princeton-nlp/SWE-bench_Verified)"
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default="data",
        help="Directory to save cached dataset (default: data)"
    )

    args = parser.parse_args()

    cache_dataset(args.dataset, args.cache_dir)


if __name__ == "__main__":
    main()
