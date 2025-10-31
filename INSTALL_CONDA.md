# Installing Conda for TDAD Thesis Project

## Why You Need Conda

Your thesis evaluation requires:
- Python 3.13 (for swebench compatibility)
- Isolated environment to avoid conflicts
- The `py313` environment referenced in EXPERIMENTS.md

## Option 1: Install Miniconda (Recommended - Smaller)

### Download and Install:

```bash
# Download Miniconda for macOS (Apple Silicon)
curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh

# Run the installer
bash Miniconda3-latest-MacOSX-arm64.sh

# Follow prompts:
# - Accept license
# - Install to default location (/Users/pepe/miniconda3)
# - Say YES to "conda init"
```

### After Installation:

```bash
# Close and reopen your terminal, OR:
source ~/.zshrc

# Verify installation
conda --version
```

## Option 2: Use Homebrew (If you prefer)

```bash
# Install conda via homebrew
brew install --cask miniconda

# Initialize conda
conda init zsh

# Restart terminal or:
source ~/.zshrc
```

## Create py313 Environment

Once conda is installed:

```bash
# Create Python 3.13 environment
conda create -n py313 python=3.13 -y

# Activate it
conda activate py313

# Verify Python version
python --version  # Should show Python 3.13.x

# Install required packages
pip install swebench datasets jsonlines

# Test it works
python -c "import swebench; print('SWE-bench installed successfully!')"
```

## Run Your Evaluation

After setup:

```bash
# Always activate first
conda activate py313

# Navigate to project
cd /Users/pepe/Development/TDAD/claudecode_n_codex_swebench

# Run evaluation
bash run_evaluation_manual.sh
```

## Troubleshooting

### Issue: "conda: command not found" after installation
**Solution:**
```bash
# Manually initialize conda
source ~/miniconda3/bin/activate
conda init zsh
source ~/.zshrc
```

### Issue: "No such file or directory: miniconda3"
**Solution:** Check where conda was installed:
```bash
find ~ -name "conda" -type f 2>/dev/null | head -5
```

### Issue: Python version wrong after activation
**Solution:**
```bash
# Remove and recreate environment
conda remove -n py313 --all
conda create -n py313 python=3.13 -y
conda activate py313
```

## Quick Installation Script

Save time by running this all at once:

```bash
#!/bin/bash
# Quick conda setup for TDAD thesis

# Download and install Miniconda
cd /tmp
curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh
bash Miniconda3-latest-MacOSX-arm64.sh -b -p $HOME/miniconda3

# Initialize conda
$HOME/miniconda3/bin/conda init zsh

# Source to make conda available
source ~/.zshrc

# Create py313 environment
conda create -n py313 python=3.13 -y

# Activate and install packages
conda activate py313
pip install swebench datasets jsonlines tqdm

echo "✅ Conda setup complete!"
echo "Run: conda activate py313"
```

## After Installation

Your shell prompt will show the active environment:
```bash
(py313) TDAD %
```

Now you can run the evaluation! See [NEXT_STEPS.md](NEXT_STEPS.md) for details.
