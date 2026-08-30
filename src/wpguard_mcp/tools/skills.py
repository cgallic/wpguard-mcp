"""In-WordPress skills repository & brand design tokens context."""
from __future__ import annotations

from ..config import get_site_registry
from ..transports import companion_plugin, ssh_wpcli


def wp_skill_save(site: str, name: str, content: str, description: str = "") -> dict:
    """Save an agent playbook / SOP into WordPress options."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        import json
        php = (
            f"$skills = get_option('wpguard_skills', []); "
            f"$skills[{repr(name)}] = ['name' => {repr(name)}, 'description' => {repr(description)}, "
            f"'content' => {repr(content)}, 'updated_at' => current_time('mysql', 1)]; "
            f"update_option('wpguard_skills', $skills, false); "
            f"echo json_encode(['saved' => true, 'name' => {repr(name)}]);"
        )
        res = ssh_wpcli.run_wp_cli(site_config, ["eval", php])
        return {"site": site, "result": json.loads(res.stdout.strip())}
    else:
        res = companion_plugin.call(
            site_config, "skill_save", {"name": name, "description": description, "content": content}
        )
        return {"site": site, "result": res}


def wp_skill_get(site: str, name: str) -> dict:
    """Retrieve an in-WordPress skill playbook by name."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        import json
        php = (
            f"$skills = get_option('wpguard_skills', []); "
            f"echo json_encode($skills[{repr(name)}] ?? ['error' => 'skill not found']);"
        )
        res = ssh_wpcli.run_wp_cli(site_config, ["eval", php])
        return {"site": site, "skill": json.loads(res.stdout.strip())}
    else:
        res = companion_plugin.call(site_config, "skill_get", {"name": name})
        return {"site": site, "skill": res}


def wp_skill_list(site: str) -> dict:
    """List all agent skills stored in WordPress."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        import json
        php = (
            "$skills = get_option('wpguard_skills', []); $sum = []; "
            "foreach ($skills as $k => $v) { $sum[] = ['name' => $k, 'description' => $v['description'] ?? '']; } "
            "echo json_encode(['skills' => $sum, 'count' => count($sum)]);"
        )
        res = ssh_wpcli.run_wp_cli(site_config, ["eval", php])
        return {"site": site, "skills": json.loads(res.stdout.strip())}
    else:
        res = companion_plugin.call(site_config, "skill_list")
        return {"site": site, "skills": res}


def wp_design_context(site: str) -> dict:
    """Extract theme global styles, color palettes, typography, and brand tokens."""
    registry = get_site_registry()
    site_config = registry.get(site)

    if site_config.transport == "ssh":
        import json
        php = (
            "$t = wp_get_theme(); "
            "$s = function_exists('wp_get_global_settings') ? wp_get_global_settings() : []; "
            "$st = function_exists('wp_get_global_styles') ? wp_get_global_styles() : []; "
            "echo json_encode(['theme' => $t->get('Name'), 'is_block' => wp_is_block_theme(), "
            "'colors' => $s['color']['palette']['theme'] ?? [], 'fonts' => $s['typography']['fontFamilies']['theme'] ?? [], 'styles' => $st]);"
        )
        res = ssh_wpcli.run_wp_cli(site_config, ["eval", php])
        return {"site": site, "design_context": json.loads(res.stdout.strip())}
    else:
        res = companion_plugin.call(site_config, "design_context")
        return {"site": site, "design_context": res}
