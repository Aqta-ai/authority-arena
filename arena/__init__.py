"""Authority Arena: a capable agent, a real objective, and authority it does not have yet.

The agent works in a small, deterministic world (a repository, CI, a shell, a deploy
service, a config store and a second agent). Every tool that can change something is
cleared by Seal at POST /v1/actions/authorize before it runs, and every decision is a
signed ACTION-v1 record. The world keeps its own effect ledger, which is the ground truth
for whether anything consequential happened without an approval.
"""

__version__ = "0.1.0"
