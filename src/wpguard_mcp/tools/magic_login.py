"""One-time magic admin login links for browser automation and visual QA."""
from __future__ import annotations

from ..config import get_site_registry
from ..transports import companion_plugin, ssh_wpcli


def wp_magic_login(site: str, user_login: str = "admin", ttl_seconds: int = 600) -> dict:
    """Generate a single-use, time-limited authenticated admin login URL."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        php = (
            f"$u = get_user_by('login', {repr(user_login)}) ?: get_users(['role' => 'administrator', 'number' => 1])[0]; "
            f"$token = wp_generate_password(32, false); "
            f"$key = 'wpguard_magic_' . hash('sha256', $token); "
            f"set_transient($key, $u->ID, {ttl_seconds}); "
            f"$url = add_query_arg(['wpguard_magic' => $token], admin_url()); "
            f"echo json_encode(['login_url' => $url, 'user_id' => $u->ID, 'user_login' => $u->user_login, 'expires_in' => {ttl_seconds}]);"
        )
        res = ssh_wpcli.run_wp_cli(site_config, ["eval", php])
        import json
        return {"site": site, "magic_login": json.loads(res.stdout.strip())}
    else:
        res = companion_plugin.call(
            site_config, "magic_login", {"user_login": user_login, "ttl_seconds": ttl_seconds}
        )
        return {"site": site, "magic_login": res}
