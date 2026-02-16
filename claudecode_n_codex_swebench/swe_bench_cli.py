#!/usr/bin/env python3

import argparse
import sys
import os
import subprocess
from pathlib import Path

def run_command(args):
    """Run the benchmark with the given arguments."""
    # Import here to avoid circular imports
    from swe_bench import main as swe_main
    
    # Set up the dataset path
    dataset = args.dataset or "princeton-nlp/SWE-bench"
    
    # Call the main swe_bench function with proper arguments
    swe_main(
        limit=args.limit,
        no_eval=args.no_eval,
        dataset=dataset,
        quick=args.quick,
        standard=args.standard,
        full=args.full,
        check=args.check,
        model_name=args.model_name,
        output_dir=args.output_dir,
        predictions=args.predictions,
        prediction_file=args.prediction_file,
        verbose=args.verbose,
        dry_run=args.dry_run,
        force=args.force,
        skip=args.skip,
        timeout=args.timeout,
        max_workers=args.max_workers,
        log_level=args.log_level,
        save=args.save,
        load=args.load,
        debug=args.debug,
        dry_run=args.dry_run,
        quiet=args.quiet,
        interactive=args.interactive,
        force=args.force,
        skip=args.skip,
        timeout=args.timeout,
        max_workers=args.max_workers,
        log_level=args.log_level,
        save=args.save,
        load=args.load,
        debug=args.debug,
        quiet=args.quiet,
        interactive=args.interactive,
        force=args.force,
        skip=args.skip,
        timeout=args.timeout,
        max_workers=args.max_workers,
        log_level=args.log_level,
        save=args.save,
        load=args.load,
        debug=args.debug,
        quiet=args.quiet,
        interactive=args.interactive,
    )

def main():
    parser = argparse.ArgumentParser(
        description="SWE-bench Benchmark Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s run --limit 10
  %(prog)s run --quick
  %(prog)s run --full
  %(prog)s run --standard
  %(prog)s run --check
  %(prog)s eval --predictions path/to/predictions.json
  %(prog)s scores
  %(prog)s quick
  %(prog)s full
  %(prog)s check
  %(prog)s list-models
        """
    )
    
    # Create subparsers for different commands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Run command
    run_parser = subparsers.add_parser('run', help='Run the benchmark')
    run_parser.add_argument('--limit', type=int, help='Limit the number of instances')
    run_parser.add_argument('--no-eval', action='store_true', help='Skip evaluation')
    run_parser.add_argument('--dataset', help='Dataset name (default: princeton-nlp/SWE-bench)')
    run_parser.add_argument('--quick', action='store_true', help='Run quick benchmark')
    run_parser.add_argument('--standard', action='store_true', help='Run standard benchmark')
    run_parser.add_argument('--full', action='store_true', help='Run full benchmark')
    run_parser.add_argument('--check', action='store_true', help='Run check benchmark')
    run_parser.add_argument('--model-name', help='Model name to use')
    run_parser.add_argument('--output-dir', help='Output directory')
    run_parser.add_argument('--predictions', help='Predictions directory')
    run_parser.add_argument('--prediction-file', help='Prediction file')
    run_parser.add_argument('--verbose', action='store_true', help='Verbose output')
    run_parser.add_argument('--dry-run', action='store_true', help='Dry run')
    run_parser.add_argument('--force', action='store_true', help='Force operation')
    run_parser.add_argument('--skip', action='store_true', help='Skip operation')
    run_parser.add_argument('--timeout', type=int, help='Timeout in seconds')
    run_parser.add_argument('--max-workers', type=int, help='Maximum workers')
    run_parser.add_argument('--log-level', help='Log level')
    run_parser.add_argument('--save', action='store_true', help='Save results')
    run_parser.add_argument('--load', action='store_true', help='Load results')
    run_parser.add_argument('--debug', action='store_true', help='Debug mode')
    run_parser.add_argument('--quiet', action='store_true', help='Quiet mode')
    run_parser.add_argument('--interactive', action='store_true', help='Interactive mode')
    
    # Eval command
    eval_parser = subparsers.add_parser('eval', help='Evaluate predictions')
    eval_parser.add_argument('--predictions', help='Predictions directory')
    eval_parser.add_argument('--prediction-file', help='Prediction file')
    
    # Scores command
    subparsers.add_parser('scores', help='Show scores')
    
    # Quick command (shortcut)
    subparsers.add_parser('quick', help='Quick benchmark')
    
    # Full command (shortcut)
    subparsers.add_parser('full', help='Full benchmark')
    
    # Check command (shortcut)
    subparsers.add_parser('check', help='Check benchmark')
    
    # List models command
    subparsers.add_parser('list-models', help='List available models')
    
    # Parse arguments
    args = parser.parse_args()
    
    # Handle shortcut commands
    if args.command == 'quick':
        args.quick = True
        args.no_eval = False
        args.dataset = "princeton-nlp/SWE-bench"
        run_command(args)
    elif args.command == 'full':
        args.full = True
        args.no_eval = False
        args.dataset = "princeton-nlp/SWE-bench"
        run_command(args)
    elif args.command == 'check':
        args.check = True
        args.no_eval = False
        args.dataset = "princeton-nlp/SWE-bench"
        run_command(args)
    elif args.command == 'eval':
        # Handle eval command
        from swe_bench import evaluate
        evaluate(args.predictions, args.prediction_file)
    elif args.command == 'scores':
        # Handle scores command
        from swe_bench import show_scores
        show_scores()
    elif args.command == 'list-models':
        # Handle list-models command
        from swe_bench import list_models
        list_models()
    elif args.command == 'run':
        # Handle run command
        run_command(args)
    else:
        # Default to run command if no command specified
        run_command(args)

if __name__ == "__main__":
    sys.exit(main())
