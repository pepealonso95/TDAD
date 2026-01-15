#!/bin/bash

# Test script for qwen-code with Ollama

# Configure Ollama as OpenAI-compatible backend
export OPENAI_API_KEY="ollama"
export OPENAI_BASE_URL="http://localhost:11434/v1"
export OPENAI_MODEL="qwen3-coder:30b"

# Test with a simple coding task
echo "Testing qwen-code with Ollama..."
echo "Write a Python function to check if a number is prime" | qwen --yolo
