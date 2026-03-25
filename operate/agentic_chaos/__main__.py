"""Allow running as: python -m agentic_chaos.cli ..."""
from .cli import main
import sys

sys.exit(main())
