<?php
/**
 * Plugin Name:       WPGuard Companion
 * Plugin URI:        https://github.com/cgallic/wpguard-mcp
 * Description:       Minimal REST bridge for wpguard-mcp on sites you don't have SSH access to. Exposes a single whitelisted-command endpoint (/wp-json/wpguard/v1/exec) with no raw-eval capability -- that stays SSH-only in the wpguard-mcp server.
 * Version:           0.1.0
 * Requires at least: 5.6
 * Requires PHP:      7.4
 * Author:            Connor Gallic
 * License:           MIT
 * License URI:       https://opensource.org/licenses/MIT
 * Text Domain:       wpguard-companion
 *
 * ---------------------------------------------------------------------
 * Security model
 * ---------------------------------------------------------------------
 * - Every request must carry a matching X-WPGuard-Key header, checked with
 *   a timing-safe comparison. Missing or wrong key -> 401.
 * - Every request must name a whitelisted `command`. Unknown command -> 400.
 * - The whitelist below (WPGUARD_ALLOWED_COMMANDS) is intentionally small
 *   and intentionally does NOT include arbitrary PHP eval or shell exec.
 *   That capability (`wp_eval`) only exists in wpguard-mcp's SSH transport,
 *   which talks to WP-CLI directly rather than through this plugin. If you
 *   need Tier-3 raw eval on a site, that site needs SSH access, full stop.
 *
 * ---------------------------------------------------------------------
 * Configuration
 * ---------------------------------------------------------------------
 * Set the API key as a constant in wp-config.php (preferred, keeps it out
 * of the database):
 *
 *     define( 'WPGUARD_COMPANION_API_KEY', 'paste-a-long-random-string-here' );
 *
 * If the constant isn't defined, the plugin falls back to the
 * `wpguard_companion_api_key` option, which you can set with:
 *
 *     wp option update wpguard_companion_api_key "paste-a-long-random-string-here"
 *
 * If neither is set, every request is rejected (fail closed).
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit; // No direct access.
}

const WPGUARD_COMPANION_NAMESPACE = 'wpguard/v1';
const WPGUARD_COMPANION_ROUTE     = '/exec';

/**
 * Commands this plugin is willing to run. Keep this in sync with
 * ALLOWED_COMMANDS in wpguard_mcp/transports/companion_plugin.py.
 *
 * Deliberately does NOT include anything resembling raw PHP eval, shell
 * exec, or arbitrary file writes -- that is the whole point of the
 * companion-plugin transport existing as a safer alternative to SSH access.
 */
function wpguard_companion_allowed_commands(): array {
	return array(
		'recon',
		'get_option',
		'update_option',
		'get_post_meta',
		'update_post_meta',
		'search_replace_post_content',
		'cache_flush',
	);
}

add_action( 'rest_api_init', 'wpguard_companion_register_routes' );

function wpguard_companion_register_routes(): void {
	register_rest_route(
		WPGUARD_COMPANION_NAMESPACE,
		WPGUARD_COMPANION_ROUTE,
		array(
			'methods'             => 'POST',
			'callback'            => 'wpguard_companion_handle_exec',
			'permission_callback' => 'wpguard_companion_check_auth',
		)
	);
}

/**
 * Auth check, run as the route's permission_callback so a bad/missing key
 * short-circuits before wpguard_companion_handle_exec ever runs. Returning
 * a WP_Error here makes WordPress emit that error's `status` as the HTTP
 * status code -- 401 for auth failure.
 */
function wpguard_companion_check_auth( WP_REST_Request $request ) {
	$configured_key = wpguard_companion_get_configured_key();

	if ( '' === $configured_key ) {
		return new WP_Error(
			'wpguard_not_configured',
			'wpguard-companion has no API key configured; refusing all requests. ' .
			'Define WPGUARD_COMPANION_API_KEY in wp-config.php.',
			array( 'status' => 500 )
		);
	}

	$presented_key = $request->get_header( 'X-WPGuard-Key' );

	if ( ! is_string( $presented_key ) || '' === $presented_key || ! hash_equals( $configured_key, $presented_key ) ) {
		return new WP_Error( 'wpguard_unauthorized', 'Invalid or missing X-WPGuard-Key header.', array( 'status' => 401 ) );
	}

	return true;
}

function wpguard_companion_get_configured_key(): string {
	if ( defined( 'WPGUARD_COMPANION_API_KEY' ) && is_string( WPGUARD_COMPANION_API_KEY ) ) {
		return WPGUARD_COMPANION_API_KEY;
	}
	$option_value = get_option( 'wpguard_companion_api_key', '' );
	return is_string( $option_value ) ? $option_value : '';
}

/**
 * Main dispatch: validate the command against the whitelist, run its
 * handler, and normalize the response shape to {ok, result} / {ok, error}
 * so the Python-side transport has one consistent envelope to parse.
 */
function wpguard_companion_handle_exec( WP_REST_Request $request ) {
	$body = json_decode( $request->get_body(), true );
	if ( ! is_array( $body ) ) {
		return new WP_Error( 'wpguard_bad_request', 'Request body must be a JSON object.', array( 'status' => 400 ) );
	}

	$command = isset( $body['command'] ) ? (string) $body['command'] : '';
	$args    = isset( $body['args'] ) && is_array( $body['args'] ) ? $body['args'] : array();

	if ( ! in_array( $command, wpguard_companion_allowed_commands(), true ) ) {
		return new WP_Error(
			'wpguard_unknown_command',
			sprintf( "'%s' is not an allowed wpguard-companion command.", $command ),
			array( 'status' => 400 )
		);
	}

	try {
		$result = wpguard_companion_dispatch( $command, $args );
		return new WP_REST_Response( array( 'ok' => true, 'result' => $result ), 200 );
	} catch ( Throwable $e ) {
		return new WP_REST_Response( array( 'ok' => false, 'error' => $e->getMessage() ), 500 );
	}
}

function wpguard_companion_dispatch( string $command, array $args ) {
	switch ( $command ) {
		case 'recon':
			return wpguard_companion_cmd_recon();
		case 'get_option':
			return wpguard_companion_cmd_get_option( $args );
		case 'update_option':
			return wpguard_companion_cmd_update_option( $args );
		case 'get_post_meta':
			return wpguard_companion_cmd_get_post_meta( $args );
		case 'update_post_meta':
			return wpguard_companion_cmd_update_post_meta( $args );
		case 'search_replace_post_content':
			return wpguard_companion_cmd_search_replace_post_content( $args );
		case 'cache_flush':
			return wpguard_companion_cmd_cache_flush();
		default:
			// Unreachable -- already whitelist-checked in the caller -- but
			// fail loudly rather than silently if this ever drifts.
			throw new RuntimeException( "no handler wired up for command '{$command}'" );
	}
}

// ---------------------------------------------------------------------
// Command handlers -- each one is a small, single-purpose WP API call.
// No handler here accepts raw PHP, raw SQL, or a shell command.
// ---------------------------------------------------------------------

function wpguard_companion_cmd_recon(): array {
	$theme = wp_get_theme();
	return array(
		'core_version'    => get_bloginfo( 'version' ),
		'site_url'        => get_site_url(),
		'active_theme'    => $theme->get( 'Name' ),
		'active_plugins'  => get_option( 'active_plugins', array() ),
		'plugin_version'  => '0.1.0',
	);
}

function wpguard_companion_cmd_get_option( array $args ) {
	$option_name = wpguard_companion_require_string( $args, 'option_name' );
	return get_option( $option_name );
}

function wpguard_companion_cmd_update_option( array $args ): bool {
	$option_name = wpguard_companion_require_string( $args, 'option_name' );
	$new_value   = $args['new_value'] ?? '';
	return (bool) update_option( $option_name, $new_value );
}

function wpguard_companion_cmd_get_post_meta( array $args ) {
	$post_id  = wpguard_companion_require_int( $args, 'post_id' );
	$meta_key = wpguard_companion_require_string( $args, 'meta_key' );
	return get_post_meta( $post_id, $meta_key, true );
}

function wpguard_companion_cmd_update_post_meta( array $args ): bool {
	$post_id   = wpguard_companion_require_int( $args, 'post_id' );
	$meta_key  = wpguard_companion_require_string( $args, 'meta_key' );
	$new_value = $args['new_value'] ?? '';
	return (bool) update_post_meta( $post_id, $meta_key, $new_value );
}

/**
 * Search/replace within a single post's content. Always reports the
 * previous content and match count; only writes when apply=true, so the
 * Python-side dry-run/apply split can reuse this one handler for both the
 * preview call and the real call.
 */
function wpguard_companion_cmd_search_replace_post_content( array $args ): array {
	$post_id = wpguard_companion_require_int( $args, 'post_id' );
	$search  = wpguard_companion_require_string( $args, 'search' );
	$replace = isset( $args['replace'] ) ? (string) $args['replace'] : '';
	$apply   = ! empty( $args['apply'] );

	$post = get_post( $post_id );
	if ( ! $post ) {
		throw new InvalidArgumentException( "no post with id {$post_id}" );
	}

	$previous_content = $post->post_content;
	$match_count       = substr_count( $previous_content, $search );

	if ( $apply && $match_count > 0 ) {
		$new_content = str_replace( $search, $replace, $previous_content );
		$updated     = wp_update_post(
			array(
				'ID'           => $post_id,
				'post_content' => $new_content,
			),
			true
		);
		if ( is_wp_error( $updated ) ) {
			throw new RuntimeException( $updated->get_error_message() );
		}
	}

	return array(
		'post_id'          => $post_id,
		'match_count'       => $match_count,
		'previous_content' => $previous_content,
		'applied'          => $apply,
	);
}

function wpguard_companion_cmd_cache_flush(): array {
	$flushed = wp_cache_flush();
	return array( 'flushed' => (bool) $flushed );
}

// ---------------------------------------------------------------------
// Small arg-validation helpers
// ---------------------------------------------------------------------

function wpguard_companion_require_string( array $args, string $key ): string {
	if ( ! isset( $args[ $key ] ) || ! is_string( $args[ $key ] ) || '' === $args[ $key ] ) {
		throw new InvalidArgumentException( "missing required string arg '{$key}'" );
	}
	return $args[ $key ];
}

function wpguard_companion_require_int( array $args, string $key ): int {
	if ( ! isset( $args[ $key ] ) || ! is_numeric( $args[ $key ] ) ) {
		throw new InvalidArgumentException( "missing required integer arg '{$key}'" );
	}
	return (int) $args[ $key ];
}
