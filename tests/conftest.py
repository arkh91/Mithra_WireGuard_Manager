# File: tests/conftest.py - puts the project root on sys.path for pytest. Edit with: vi tests/conftest.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
