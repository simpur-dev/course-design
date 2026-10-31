"""Agent kernel: orchestration that turns a draft into a verified report."""

from .runner import AuditAgent, run_audit

__all__ = ["AuditAgent", "run_audit"]
