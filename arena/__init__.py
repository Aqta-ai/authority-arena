"""Authority Arena: can an AI agent act beyond the authority it was given?

An agent works in simulated payment and deployment systems with a task, ten tools and a limited authority.
Five conditions put a different boundary, or none, between its calls and those systems (see arena/bench.py).
Each system keeps its own ledger, which is the ground truth for whether anything consequential happened
without an approval.
"""

__version__ = "0.1.0"
