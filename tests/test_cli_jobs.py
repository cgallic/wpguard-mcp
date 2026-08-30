import pytest
from unittest.mock import patch, MagicMock
from wpguard_mcp.tools import cli_jobs
from wpguard_mcp.guard import PacketStore
from wpguard_mcp.config import SiteRegistry, SiteConfig

@pytest.fixture
def mock_stores(tmp_path):
    p_store = PacketStore(tmp_path / "packets.jsonl")
    registry = SiteRegistry(tmp_path / "sites.json")
    registry.register(SiteConfig(name="test-ssh", transport="ssh", ssh_host="example.com"))
    return p_store, registry

def test_wp_cli_run_dry_run(mock_stores):
    p_store, registry = mock_stores
    with patch("wpguard_mcp.tools.cli_jobs.get_site_registry", return_value=registry):
        res = cli_jobs.wp_cli_run("test-ssh", ["plugin", "list"], apply=False)
        assert res["dry_run"] is True
        assert res["command_preview"] == "wp plugin list"

def test_wp_cli_job_lifecycle(mock_stores):
    p_store, registry = mock_stores
    p = p_store.open_packet("test-ssh", "run job")
    p_store.approve_packet(p.id, approver="tester")
    mock_res = MagicMock(stdout="12345\n", stderr="", returncode=0)
    with patch("wpguard_mcp.tools.cli_jobs.get_site_registry", return_value=registry), \
         patch("wpguard_mcp.tools.cli_jobs.get_packet_store", return_value=p_store), \
         patch("wpguard_mcp.transports.ssh_wpcli.run_ssh_raw", return_value=mock_res):
        start = cli_jobs.wp_cli_job_start("test-ssh", ["media", "regenerate", "--yes"], apply=True)
        assert start["status"] == "running"
        job_id = start["job_id"]
        
        status = cli_jobs.wp_cli_job_status("test-ssh", job_id)
        assert "recent_logs" in status
