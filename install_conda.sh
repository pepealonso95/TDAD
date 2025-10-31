#!/bin/bash
# Quick conda setup for TDAD thesis project
# Usage: bash install_conda.sh

set -e

echo "================================================================"
echo "TDAD Thesis - Conda Installation"
echo "================================================================"
echo ""
echo "This script will:"
echo "  1. Download and install Miniconda"
echo "  2. Create py313 environment with Python 3.13"
echo "  3. Install required packages (swebench, datasets, etc.)"
echo ""
echo "Press Ctrl+C to cancel, or Enter to continue..."
read

echo ""
echo "Step 1/4: Downloading Miniconda..."
cd /tmp
curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh

echo ""
echo "Step 2/4: Installing Miniconda..."
echo "  (This will take a few minutes)"
bash Miniconda3-latest-MacOSX-arm64.sh -b -p $HOME/miniconda3

echo ""
echo "Step 3/4: Initializing conda for zsh..."
$HOME/miniconda3/bin/conda init zsh

echo ""
echo "Step 4/4: Creating py313 environment..."
# Need to source conda first
source $HOME/miniconda3/etc/profile.d/conda.sh
conda create -n py313 python=3.13 -y

echo ""
echo "Installing required packages..."
conda activate py313
pip install swebench datasets jsonlines tqdm

echo ""
echo "================================================================"
echo "✅ Installation Complete!"
echo "================================================================"
echo ""
echo "Next steps:"
echo "  1. Close and reopen your terminal (or run: source ~/.zshrc)"
echo "  2. Activate environment: conda activate py313"
echo "  3. Run evaluation: cd /Users/pepe/Development/TDAD/claudecode_n_codex_swebench"
echo "  4. Then: bash run_evaluation_manual.sh"
echo ""
echo "Your terminal prompt will show: (py313) when activated"
echo "================================================================"
