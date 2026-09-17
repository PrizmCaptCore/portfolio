"""Entry point:  python -m module   (run from the repo root)

    BACKEND=small  python -m module          # full window 4/15-5/9
    BACKEND=claude python -m module
"""
from .pipeline import run_firehose

if __name__ == "__main__":
    run_firehose()
