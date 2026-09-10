"""wpguard-mcp tool modules."""
from . import (
    blocks,
    cli_jobs,
    eval_sandbox,
    files,
    magic_login,
    mutate,
    packets,
    pages,
    preapprovals,
    recon,
    revisions,
    rollback,
    schema_recon,
    skills,
    staging,
    updates,
    vulnerabilities,
)

__all__ = [
    "blocks",
    "cli_jobs",
    "eval_sandbox",
    "files",
    "magic_login",
    "mutate",
    "packets",
    "pages",
    "preapprovals",
    "recon",
    "revisions",
    "rollback",
    "schema_recon",
    "skills",
    "staging",
    "updates",
    "vulnerabilities",
]

# One importable registry for every operation that can write only after the
# shared packet gate. Individual modules retain their local registries so their
# focused tests can patch the gate at the module boundary.
GUARDED_TOOLS = {
    **mutate.GUARDED_TOOLS,
    **pages.GUARDED_TOOLS,
    **blocks.GUARDED_TOOLS,
    **revisions.GUARDED_TOOLS,
    **updates.GUARDED_TOOLS,
}
