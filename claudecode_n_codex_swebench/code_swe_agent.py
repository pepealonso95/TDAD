#!/usr/bin/env python3
"""
SWE-bench agent capable of using Claude Code or Codex backends.
"""

import argparse
import json
import os
import sys
import subprocess
import tempfile
import shutil
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path

from datasets import load_dataset
from tqdm import tqdm
import jsonlines

from utils.claude_interface import ClaudeCodeInterface
from utils.codex_interface import CodexCodeInterface
from utils.qwen_interface import QwenCodeInterface
from utils.gptoss_interface import GPTOSSCodeInterface
from utils.ccr_interface import CCRCodeInterface
from utils.prompt_formatter import PromptFormatter
from utils.patch_extractor import PatchExtractor
from utils.model_registry import get_model_name


DEFAULT_BACKEND = os.environ.get("CODE_SWE_BACKEND", "claude")
CACHE_DIR = Path(__file__).parent / "data"


def load_cached_dataset(dataset_name: str, split: str = "test"):
    """Load dataset from local cache if available, otherwise from HuggingFace."""
    cache_path = CACHE_DIR / (dataset_name.replace("/", "_") + ".json")

    if cache_path.exists():
        print(f"Loading from cache: {cache_path}")
        with open(cache_path, 'r') as f:
            data = json.load(f)
        print(f"Loaded {len(data)} instances from cache")
        return data

    print(f"Cache not found at {cache_path}, downloading from HuggingFace...")
    print(f"(Run 'python cache_dataset.py --dataset {dataset_name}' to cache it)")
    return load_dataset(dataset_name, split=split)


class CodeSWEAgent:
    """Main agent for running SWE-bench using different code models."""

    def __init__(self, prompt_template: Optional[str] = None,
                 model: Optional[str] = None,
                 backend: str = DEFAULT_BACKEND,
                 tdd_mode: bool = False):
        self.backend = (backend or DEFAULT_BACKEND).lower()
        self.tdd_mode = tdd_mode
        if self.backend == "codex":
            self.interface = CodexCodeInterface()
        elif self.backend == "qwen":
            self.interface = QwenCodeInterface()
        elif self.backend == "gptoss":
            self.interface = GPTOSSCodeInterface()
        elif self.backend == "ccr":
            self.interface = CCRCodeInterface()
        else:
            self.backend = "claude"
            self.interface = ClaudeCodeInterface()

        self.prompt_formatter = PromptFormatter(prompt_template)
        self.patch_extractor = PatchExtractor()
        self.base_dir = Path.cwd()
        self.results_dir = self.base_dir / "results"
        self.predictions_dir = self.base_dir / "predictions"

        # Resolve model name from alias
        self.model = get_model_name(model, self.backend) if model else None
        self.model_alias = model  # Keep original alias for logging

        # Create directories if they don't exist
        self.results_dir.mkdir(exist_ok=True)
        self.predictions_dir.mkdir(exist_ok=True)
        self.pred_timestamp: Optional[str] = None
        self.pred_file: Optional[Path] = None

    def setup_repository(self, instance: Dict) -> Optional[str]:
        """Set up a repository for testing."""
        instance_id = instance["instance_id"]
        repo_name = instance["repo"]
        base_commit = instance["base_commit"]

        # Create temporary directory for this instance (cross-platform)
        temp_dir = Path(tempfile.gettempdir()) / f"swe_bench_{instance_id}"

        try:
            # Remove if exists
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

            # Save current directory
            original_dir = Path.cwd()
            
            # Clone repository
            print(f"Cloning {repo_name} to {temp_dir}")
            clone_url = f"https://github.com/{repo_name}.git"
            
            result = subprocess.run(
                ["git", "clone", clone_url, str(temp_dir)],
                capture_output=True,
                text=True,
                cwd=str(original_dir)  # Ensure we're in a valid directory
            )
            
            if result.returncode != 0:
                print(f"Failed to clone repository: {result.stderr}")
                return None
                
            # Checkout base commit
            os.chdir(temp_dir)
            result = subprocess.run(
                ["git", "checkout", base_commit],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                print(f"Failed to checkout commit: {result.stderr}")
                os.chdir(str(original_dir))  # Return to original directory
                return None

            os.chdir(str(original_dir))  # Return to original directory
            return str(temp_dir)
            
        except Exception as e:
            print(f"Error setting up repository: {e}")
            # Try to return to original directory if possible
            try:
                os.chdir(str(original_dir))
            except Exception as chdir_error:
                print(f"Warning: Failed to return to original directory: {chdir_error}")
            return None
            
    def process_instance(self, instance: Dict) -> Dict:
        """Process a single SWE-bench instance."""
        instance_id = instance["instance_id"]
        print(f"\nProcessing {instance_id}")

        original_dir = os.getcwd()

        repo_path = self.setup_repository(instance)
        if not repo_path:
            return {
                "instance_id": instance_id,
                "model": f"{self.backend}-code",
                "prediction": "",
                "error": "Failed to set up repository",
            }

        try:
            prompt = self.prompt_formatter.format_for_cli(instance)

            os.chdir(repo_path)
            subprocess.run(["git", "add", "-A"], capture_output=True)
            subprocess.run(["git", "stash"], capture_output=True)

            model_info = f" with model {self.model_alias}" if self.model else ""
            tdd_info = " (TDD mode)" if self.tdd_mode else ""
            print(f"Running {self.backend.title()} Code{model_info}{tdd_info}...")

            # Only qwen backend supports tdd_mode
            if self.backend == "qwen":
                result = self.interface.execute_code_cli(prompt, repo_path, self.model, tdd_mode=self.tdd_mode)
            else:
                result = self.interface.execute_code_cli(prompt, repo_path, self.model)

            if not result["success"]:
                print(f"{self.backend.title()} Code execution failed: {result['stderr']}")
                os.chdir(original_dir)
                return {
                    "instance_id": instance_id,
                    "model": self.model_alias or f"{self.backend}-code",
                    "prediction": "",
                    "error": f"Execution failed: {result['stderr']}",
                }

            patch = self.patch_extractor.extract_from_cli_output(result["stdout"], repo_path)

            is_valid, error = self.patch_extractor.validate_patch(patch)
            if not is_valid:
                print(f"Invalid patch: {error}")
                patch = ""

            prediction = self.patch_extractor.format_for_swebench(
                patch, instance_id, self.model_alias or f"{self.backend}-code"
            )

            self._save_result(instance_id, result, patch)

            return prediction

        except Exception as e:
            import traceback
            print(f"Error processing instance: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            return {
                "instance_id": instance_id,
                "model": self.model_alias or f"{self.backend}-code",
                "prediction": "",
                "error": str(e),
            }
        finally:
            try:
                os.chdir(original_dir)
            except Exception as e:
                print(f"Warning: Could not restore directory: {e}")

            if repo_path and os.path.exists(repo_path):
                shutil.rmtree(repo_path)
    def _save_result(self, instance_id: str, result: Dict, patch: str):
        """Save detailed results for debugging."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_file = self.results_dir / f"{instance_id}_{timestamp}.json"
        
        with open(result_file, 'w') as f:
            json.dump({
                "instance_id": instance_id,
                "timestamp": timestamp,
                "claude_output": result,
                "extracted_patch": patch
            }, f, indent=2)
            
    def run_on_dataset(self, dataset_name: str, split: str = "test",
                      limit: Optional[int] = None) -> List[Dict]:
        """Run on a full dataset."""
        print(f"Loading dataset: {dataset_name}")
        dataset = load_cached_dataset(dataset_name, split=split)
        
        if limit:
            # Handle both HuggingFace Dataset and plain list from cache
            if hasattr(dataset, 'select'):
                dataset = dataset.select(range(min(limit, len(dataset))))
            else:
                dataset = dataset[:min(limit, len(dataset))]
            
        self.pred_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.pred_file = self.predictions_dir / f"predictions_{self.pred_timestamp}.jsonl"
        if self.pred_file.exists():
            self.pred_file.unlink()
        json_file = self.predictions_dir / f"predictions_{self.pred_timestamp}.json"
        if json_file.exists():
            json_file.unlink()

        predictions: List[Dict] = []

        for instance in tqdm(dataset, desc="Processing instances"):
            prediction = self.process_instance(instance)
            predictions.append(prediction)

            # Save prediction incrementally
            self._save_predictions(prediction)

        with open(json_file, 'w') as f:
            json.dump(predictions, f, indent=2)

        print(f"Saved predictions to {self.pred_file}")
        return predictions
    
    def run_on_instance(self, instance_id: str, dataset_name: str = "princeton-nlp/SWE-bench_Lite") -> Dict:
        """Run on a single instance by ID."""
        dataset = load_cached_dataset(dataset_name, split="test")
        
        # Find the instance
        instance = None
        for item in dataset:
            if item["instance_id"] == instance_id:
                instance = item
                break
                
        if not instance:
            raise ValueError(f"Instance {instance_id} not found in dataset")
            
        return self.process_instance(instance)
    
    def _save_predictions(self, prediction: Dict):
        """Append a single prediction to the jsonl file."""
        if not self.pred_file:
            raise ValueError("Prediction timestamp not initialized. Call run_on_dataset first.")

        with jsonlines.open(self.pred_file, mode='a') as writer:
            writer.write(prediction)


def main():
    parser = argparse.ArgumentParser(description="Run code models on SWE-bench")
    parser.add_argument("--dataset_name", type=str,
                       default="princeton-nlp/SWE-bench_Lite",
                       help="Dataset to use")
    parser.add_argument("--instance_id", type=str,
                       help="Run on a specific instance ID")
    parser.add_argument("--limit", type=int,
                       help="Limit number of instances to process")
    parser.add_argument("--prompt_template", type=str,
                       help="Path to custom prompt template")
    parser.add_argument("--model", type=str,
                       help="Model to use (e.g., opus-4.1, codex-4.2, or any name)")
    parser.add_argument("--backend", type=str, choices=["claude", "codex", "qwen", "gptoss", "ccr"],
                       help="Code model backend to use (claude, codex, qwen, gptoss, or ccr)")
    parser.add_argument("--tdd", action="store_true",
                       help="Use TDD mode - generate tests first, then implementation (only works with qwen backend)")

    args = parser.parse_args()
    
    backend = args.backend or DEFAULT_BACKEND

    # Check if selected CLI is available (skip for qwen, gptoss, and ccr which use their own interfaces)
    if backend not in ["qwen", "gptoss", "ccr"]:
        cli_cmd = "codex" if backend == "codex" else "claude"
        try:
            result = subprocess.run([cli_cmd, "--version"], capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Error: {cli_cmd} CLI not found. Please ensure '{cli_cmd}' is installed and in PATH")
                sys.exit(1)
        except FileNotFoundError:
            print(f"Error: {cli_cmd} CLI not found. Please ensure '{cli_cmd}' is installed and in PATH")
            sys.exit(1)

    # Warn if TDD mode used with non-qwen backend
    if args.tdd and backend != "qwen":
        print(f"Warning: --tdd flag only works with qwen backend, ignoring for {backend}")

    agent = CodeSWEAgent(args.prompt_template, args.model, backend, tdd_mode=args.tdd)

    # Run on specific instance or dataset
    if args.instance_id:
        print(f"Running on instance: {args.instance_id}")
        prediction = agent.run_on_instance(args.instance_id, args.dataset_name)
        print(f"Prediction saved: {prediction}")
    else:
        print(f"Running on dataset: {args.dataset_name}")
        predictions = agent.run_on_dataset(args.dataset_name, limit=args.limit)
        print(f"Processed {len(predictions)} instances")


if __name__ == "__main__":
    main()
