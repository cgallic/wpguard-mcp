<?php
/**
 * Plugin Name:       WPGuard Companion
 * Plugin URI:        https://github.com/cgallic/wpguard-mcp
 * Description:       WordPress REST bridge for wpguard-mcp on sites without SSH. Provides content updates, file operations, and PHP execution for trusted operators.
 * Version:           0.4.0
 * Requires at least: 5.6
 * Requires PHP:      8.0
 * Author:            Connor Gallic
 * License:           MIT
 * License URI:       https://opensource.org/licenses/MIT
 * Text Domain:       wpguard-companion
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

const WPGUARD_COMPANION_NAMESPACE = 'wpguard/v1';
const WPGUARD_COMPANION_ROUTE     = '/exec';

// Magic login authentication hook
add_action( 'init', 'wpguard_handle_magic_login' );
function wpguard_handle_magic_login() {
	if ( isset( $_GET['wpguard_magic'] ) && ! is_user_logged_in() ) {
		$token = sanitize_text_field( wp_unslash( $_GET['wpguard_magic'] ) );
		$key = 'wpguard_magic_' . hash( 'sha256', $token );
		$user_id = get_transient( $key );
		if ( $user_id ) {
			delete_transient( $key );
			wp_set_auth_cookie( $user_id );
			wp_safe_redirect( admin_url() );
			exit;
		}
	}
}

function wpguard_companion_allowed_commands(): array {
	return array(
		'recon',
		'get_option',
		'update_option',
		'get_post_meta',
		'update_post_meta',
		'search_replace_post_content',
		'page_list',
		'page_get',
		'page_replace_content',
		'post_content_get',
		'post_content_replace',
		'revision_list',
		'revision_get',
		'revision_find',
		'revision_revert',
		'cache_flush',
		'eval_sandbox',
		'file_read',
		'file_write',
		'file_edit',
		'file_tree',
		'file_delete',
		'snippet_save',
		'snippet_toggle',
		'snippet_list',
		'block_parse',
		'block_compose',
		'post_create',
		'magic_login',
		'skill_save',
		'skill_get',
		'skill_list',
		'design_context',
		'schema_recon',
		'db_query',
	);
}

function wpguard_companion_expected_api_key(): ?string {
	if ( defined( 'WPGUARD_COMPANION_API_KEY' ) && WPGUARD_COMPANION_API_KEY ) {
		return (string) WPGUARD_COMPANION_API_KEY;
	}
	$opt = get_option( 'wpguard_companion_api_key', '' );
	return $opt ? (string) $opt : null;
}

add_action( 'rest_api_init', 'wpguard_companion_register_route' );
function wpguard_companion_register_route(): void {
	register_rest_route(
		WPGUARD_COMPANION_NAMESPACE,
		WPGUARD_COMPANION_ROUTE,
		array(
			'methods'             => WP_REST_Server::CREATABLE,
			'callback'            => 'wpguard_companion_handle_exec',
			'permission_callback' => 'wpguard_companion_authorize',
			'args'                => array(
				'command' => array(
					'required'          => true,
					'type'              => 'string',
					'sanitize_callback' => 'sanitize_text_field',
				),
				'args'    => array(
					'required' => false,
					'type'     => 'object',
					'default'  => array(),
				),
			),
		)
	);
}

function wpguard_companion_authorize( WP_REST_Request $request ) {
	// WordPress Application Passwords authenticate REST requests as a real user.
	// Prefer that core-native identity and capability check when present.
	if ( is_user_logged_in() && current_user_can( 'manage_options' ) ) {
		return true;
	}
	$expected = wpguard_companion_expected_api_key();
	if ( ! $expected ) {
		return new WP_Error( 'wpguard_not_configured', 'WPGuard companion API key is not configured on this site.', array( 'status' => 500 ) );
	}
	$key = $request->get_header( 'X-WPGuard-Key' );
	if ( ! $key || ! hash_equals( $expected, $key ) ) {
		return new WP_Error( 'wpguard_unauthorized', 'Missing or invalid X-WPGuard-Key header.', array( 'status' => 401 ) );
	}
	return true;
}

function wpguard_companion_handle_exec( WP_REST_Request $request ): WP_REST_Response {
	$command = (string) $request->get_param( 'command' );
	$args    = (array) $request->get_param( 'args' );

	if ( ! in_array( $command, wpguard_companion_allowed_commands(), true ) ) {
		return new WP_REST_Response( array( 'error' => "Command '{$command}' is not in the whitelist." ), 400 );
	}

	try {
		switch ( $command ) {
			case 'recon':
				$theme = wp_get_theme();
				$active_plugins = (array) get_option( 'active_plugins', array() );
				return new WP_REST_Response( array(
					'wp_version'     => get_bloginfo( 'version' ),
					'site_url'       => get_site_url(),
					'home_url'       => get_home_url(),
					'theme_name'     => $theme->get( 'Name' ),
					'theme_version'  => $theme->get( 'Version' ),
					'active_plugins' => $active_plugins,
					'php_version'    => PHP_VERSION,
				), 200 );

			case 'get_option':
				$opt_name = $args['option_name'] ?? '';
				if ( ! is_string( $opt_name ) || '' === $opt_name || sanitize_text_field( $opt_name ) !== $opt_name ) {
					return new WP_REST_Response( array( 'error' => 'Option name must be an exact nonempty sanitized string.' ), 400 );
				}
				return new WP_REST_Response( array( 'option_name' => $opt_name, 'value' => get_option( $opt_name, null ) ), 200 );

			case 'update_option':
				$opt_name = $args['option_name'] ?? '';
				if ( ! is_string( $opt_name ) || '' === $opt_name || sanitize_text_field( $opt_name ) !== $opt_name ) {
					return new WP_REST_Response( array( 'error' => 'Option name must be an exact nonempty sanitized string.' ), 400 );
				}
				$new_val  = $args['new_value'] ?? '';
				$prev_val = get_option( $opt_name, null );
				$expected = $args['expected_value_sha256'] ?? '';
				if ( ! is_string( $expected ) ) {
					return new WP_REST_Response( array( 'error' => 'Expected value digest must be a string.' ), 400 );
				}
				if ( '' !== $expected && ! hash_equals( hash( 'sha256', (string) $prev_val ), $expected ) ) {
					return new WP_REST_Response( array( 'error' => 'Option changed before update; read it again.' ), 409 );
				}
				$updated  = update_option( $opt_name, $new_val );
				return new WP_REST_Response( array( 'option_name' => $opt_name, 'previous_value' => $prev_val, 'new_value' => $new_val, 'updated' => $updated ), 200 );

			case 'get_post_meta':
				$pid = (int) ( $args['post_id'] ?? 0 );
				$key = $args['meta_key'] ?? '';
				if ( ! is_string( $key ) || '' === $key || sanitize_text_field( $key ) !== $key ) {
					return new WP_REST_Response( array( 'error' => 'Meta key must be an exact nonempty sanitized string.' ), 400 );
				}
				return new WP_REST_Response( array( 'post_id' => $pid, 'meta_key' => $key, 'value' => get_post_meta( $pid, $key, true ) ), 200 );

			case 'update_post_meta':
				$pid = (int) ( $args['post_id'] ?? 0 );
				$key = $args['meta_key'] ?? '';
				if ( ! is_string( $key ) || '' === $key || sanitize_text_field( $key ) !== $key ) {
					return new WP_REST_Response( array( 'error' => 'Meta key must be an exact nonempty sanitized string.' ), 400 );
				}
				$val = $args['new_value'] ?? '';
				$prev = get_post_meta( $pid, $key, true );
				$expected = $args['expected_value_sha256'] ?? '';
				if ( ! is_string( $expected ) ) {
					return new WP_REST_Response( array( 'error' => 'Expected value digest must be a string.' ), 400 );
				}
				if ( '' !== $expected && ! hash_equals( hash( 'sha256', (string) $prev ), $expected ) ) {
					return new WP_REST_Response( array( 'error' => 'Post meta changed before update; read it again.' ), 409 );
				}
				$updated = update_post_meta( $pid, $key, $val );
				return new WP_REST_Response( array( 'post_id' => $pid, 'meta_key' => $key, 'previous_value' => $prev, 'new_value' => $val, 'updated' => $updated ), 200 );

			case 'search_replace_post_content':
				$pid = (int) ( $args['post_id'] ?? 0 );
				$search = (string) ( $args['search'] ?? '' );
				$replace = (string) ( $args['replace'] ?? '' );
				$apply = (bool) ( $args['apply'] ?? false );
				if ( '' === $search ) {
					return new WP_REST_Response( array( 'error' => 'Search must not be empty.' ), 400 );
				}
				$post = get_post( $pid );
				if ( ! $post ) {
					return new WP_REST_Response( array( 'error' => "Post {$pid} not found" ), 404 );
				}
				$content = $post->post_content;
				$matches = substr_count( $content, $search );
				$new_content = str_replace( $search, $replace, $content );
				if ( $apply ) {
					$expected = $args['expected_content_sha256'] ?? '';
					if ( ! is_string( $expected ) ) {
						return new WP_REST_Response( array( 'error' => 'Expected content digest must be a string.' ), 400 );
					}
					if ( '' !== $expected && ! hash_equals( hash( 'sha256', $content ), $expected ) ) {
						return new WP_REST_Response( array( 'error' => 'Post content changed after preview; preview again.' ), 409 );
					}
					wp_update_post( array( 'ID' => $pid, 'post_content' => $new_content ) );
				}
				return new WP_REST_Response( array(
					'post_id' => $pid,
					'matches' => $matches,
					'match_count' => $matches,
					'previous_content' => $content,
					'supports_expected_content_sha256' => true,
					'applied' => $apply,
				), 200 );

			case 'page_list':
				$post_type = sanitize_key( (string) ( $args['post_type'] ?? 'page' ) );
				$post_status = sanitize_key( (string) ( $args['post_status'] ?? 'publish' ) );
				$per_page = min( 100, max( 1, (int) ( $args['per_page'] ?? 20 ) ) );
				$page_number = max( 1, (int) ( $args['page'] ?? 1 ) );
				$query = new WP_Query( array(
					'post_type' => $post_type,
					'post_status' => $post_status,
					's' => sanitize_text_field( (string) ( $args['search'] ?? '' ) ),
					'posts_per_page' => $per_page,
					'paged' => $page_number,
					'orderby' => 'modified',
					'order' => 'DESC',
				) );
				$pages = array_map( static function ( $post ) {
					return array(
						'id' => (int) $post->ID,
						'title' => get_the_title( $post ),
						'slug' => $post->post_name,
						'status' => $post->post_status,
						'modified' => $post->post_modified_gmt,
						'url' => get_permalink( $post ),
					);
				}, $query->posts );
				return new WP_REST_Response( array(
					'pages' => $pages,
					'page' => $page_number,
					'per_page' => $per_page,
					'total' => (int) $query->found_posts,
					'total_pages' => (int) $query->max_num_pages,
				), 200 );

			case 'page_get':
				$pid = (int) ( $args['post_id'] ?? 0 );
				$post = get_post( $pid );
				if ( ! $post ) {
					return new WP_REST_Response( array( 'error' => "Post {$pid} not found" ), 404 );
				}
				if ( 'page' !== $post->post_type ) {
					return new WP_REST_Response( array( 'error' => "Post {$pid} is not a page" ), 400 );
				}
				return new WP_REST_Response( array(
					'id' => (int) $post->ID,
					'title' => get_the_title( $post ),
					'slug' => $post->post_name,
					'status' => $post->post_status,
					'modified' => $post->post_modified_gmt,
					'url' => get_permalink( $post ),
					'content' => $post->post_content,
					'content_sha256' => hash( 'sha256', $post->post_content ),
				), 200 );

			case 'page_replace_content':
				$pid = (int) ( $args['post_id'] ?? 0 );
				$post = get_post( $pid );
				if ( ! $post ) {
					return new WP_REST_Response( array( 'error' => "Post {$pid} not found" ), 404 );
				}
				if ( 'page' !== $post->post_type ) {
					return new WP_REST_Response( array( 'error' => "Post {$pid} is not a page" ), 400 );
				}
				$new_content = (string) ( $args['new_content'] ?? '' );
				$expected = $args['expected_content_sha256'] ?? '';
				if ( ! is_string( $expected ) || '' === $expected ) {
					return new WP_REST_Response( array( 'error' => 'Expected content digest is required.' ), 400 );
				}
				$current_digest = hash( 'sha256', $post->post_content );
				if ( ! hash_equals( $current_digest, $expected ) ) {
					return new WP_REST_Response( array(
						'error' => 'Post content changed before replacement; read it again.',
						'current_content_sha256' => $current_digest,
					), 409 );
				}
				$updated = wp_update_post( array( 'ID' => $pid, 'post_content' => $new_content ), true );
				if ( is_wp_error( $updated ) ) {
					return new WP_REST_Response( array( 'error' => $updated->get_error_message() ), 500 );
				}
				$updated_post = get_post( $pid );
				return new WP_REST_Response( array(
					'updated' => true,
					'previous_content_sha256' => $current_digest,
					'page' => array(
						'id' => (int) $updated_post->ID,
						'title' => get_the_title( $updated_post ),
						'slug' => $updated_post->post_name,
						'status' => $updated_post->post_status,
						'modified' => $updated_post->post_modified_gmt,
						'url' => get_permalink( $updated_post ),
						'content' => $updated_post->post_content,
						'content_sha256' => hash( 'sha256', $updated_post->post_content ),
					),
				), 200 );

			case 'post_content_get':
				$pid  = (int) ( $args['post_id'] ?? 0 );
				$post = get_post( $pid );
				if ( ! $post || 'revision' === $post->post_type ) {
					return new WP_REST_Response( array( 'error' => "Post {$pid} not found" ), 404 );
				}
				return new WP_REST_Response( array(
					'id'             => (int) $post->ID,
					'post_type'      => $post->post_type,
					'title'          => get_the_title( $post ),
					'slug'           => $post->post_name,
					'status'         => $post->post_status,
					'modified'       => $post->post_modified_gmt,
					'date'           => $post->post_date_gmt,
					'url'            => get_permalink( $post ),
					'content'        => $post->post_content,
					'content_sha256' => hash( 'sha256', $post->post_content ),
				), 200 );

			case 'post_content_replace':
				$pid  = (int) ( $args['post_id'] ?? 0 );
				$post = get_post( $pid );
				if ( ! $post || 'revision' === $post->post_type ) {
					return new WP_REST_Response( array( 'error' => "Post {$pid} not found" ), 404 );
				}
				$expected = $args['expected_content_sha256'] ?? '';
				$current_digest = hash( 'sha256', $post->post_content );
				if ( ! is_string( $expected ) || '' === $expected || ! hash_equals( $current_digest, $expected ) ) {
					return new WP_REST_Response( array( 'error' => 'Post content changed before replacement.', 'current_content_sha256' => $current_digest ), 409 );
				}
				$updated = wp_update_post( array( 'ID' => $pid, 'post_content' => (string) ( $args['new_content'] ?? '' ) ), true );
				if ( is_wp_error( $updated ) ) {
					return new WP_REST_Response( array( 'error' => $updated->get_error_message() ), 500 );
				}
				$current = get_post( $pid );
				return new WP_REST_Response( array( 'updated' => true, 'content_sha256' => hash( 'sha256', $current->post_content ) ), 200 );

			case 'revision_list':
				$pid   = (int) ( $args['post_id'] ?? 0 );
				$limit = max( 1, min( 100, (int) ( $args['limit'] ?? 20 ) ) );
				$items = wp_get_post_revisions( $pid, array( 'posts_per_page' => $limit, 'orderby' => 'ID', 'order' => 'DESC' ) );
				$rows  = array();
				foreach ( $items as $revision ) {
					$rows[] = array( 'revision_id' => (int) $revision->ID, 'parent_id' => (int) $revision->post_parent, 'date' => $revision->post_date_gmt, 'modified' => $revision->post_modified_gmt, 'author' => (int) $revision->post_author );
				}
				return new WP_REST_Response( array( 'revisions' => $rows ), 200 );

			case 'revision_get':
				$pid         = (int) ( $args['post_id'] ?? 0 );
				$revision_id = (int) ( $args['revision_id'] ?? 0 );
				$revision    = get_post( $revision_id );
				if ( ! $revision || 'revision' !== $revision->post_type || (int) $revision->post_parent !== $pid ) {
					return new WP_REST_Response( array( 'error' => 'Revision does not belong to the requested post.' ), 404 );
				}
				return new WP_REST_Response( array( 'revision_id' => $revision_id, 'parent_id' => $pid, 'date' => $revision->post_date_gmt, 'modified' => $revision->post_modified_gmt, 'author' => (int) $revision->post_author, 'content' => $revision->post_content, 'content_sha256' => hash( 'sha256', $revision->post_content ) ), 200 );

			case 'revision_find':
				$pid      = (int) ( $args['post_id'] ?? 0 );
				$digest   = (string) ( $args['content_sha256'] ?? '' );
				$excluded = array_map( 'intval', (array) ( $args['exclude_revision_ids'] ?? array() ) );
				$items    = wp_get_post_revisions( $pid, array( 'posts_per_page' => 100, 'orderby' => 'ID', 'order' => 'DESC' ) );
				foreach ( $items as $revision ) {
					if ( ! in_array( (int) $revision->ID, $excluded, true ) && hash_equals( $digest, hash( 'sha256', $revision->post_content ) ) ) {
						return new WP_REST_Response( array( 'revision_id' => (int) $revision->ID, 'content_sha256' => $digest ), 200 );
					}
				}
				return new WP_REST_Response( array( 'revision_id' => null ), 200 );

			case 'revision_revert':
				$pid         = (int) ( $args['post_id'] ?? 0 );
				$revision_id = (int) ( $args['revision_id'] ?? 0 );
				$post        = get_post( $pid );
				$revision    = get_post( $revision_id );
				$expected    = (string) ( $args['expected_content_sha256'] ?? '' );
				if ( ! $post || ! $revision || 'revision' !== $revision->post_type || (int) $revision->post_parent !== $pid ) {
					return new WP_REST_Response( array( 'error' => 'Revision does not belong to the requested post.' ), 404 );
				}
				if ( '' === $expected || ! hash_equals( hash( 'sha256', $post->post_content ), $expected ) ) {
					return new WP_REST_Response( array( 'error' => 'Post changed before revision restore.' ), 409 );
				}
				$updated = wp_update_post( array( 'ID' => $pid, 'post_content' => $revision->post_content ), true );
				if ( is_wp_error( $updated ) ) {
					return new WP_REST_Response( array( 'error' => $updated->get_error_message() ), 500 );
				}
				$current = get_post( $pid );
				return new WP_REST_Response( array( 'updated' => true, 'content_sha256' => hash( 'sha256', $current->post_content ) ), 200 );

			case 'cache_flush':
				$flushed = function_exists( 'wp_cache_flush' ) ? wp_cache_flush() : false;
				return new WP_REST_Response( array( 'flushed' => $flushed ), 200 );

			case 'eval_sandbox':
				$code = $args['code'] ?? '';
				ob_start();
				$start = microtime( true );
				$error = null;
				$return_val = null;
				try {
					$return_val = eval( $code );
				} catch ( Throwable $t ) {
					$error = array( 'message' => $t->getMessage(), 'file' => $t->getFile(), 'line' => $t->getLine() );
				}
				$output = ob_get_clean();
				$dur = round( ( microtime( true ) - $start ) * 1000, 2 );
				return new WP_REST_Response( array( 'success' => ( $error === null ), 'output' => $output, 'return_value' => $return_val, 'error' => $error, 'duration_ms' => $dur ), 200 );

			case 'file_read':
				$rel = $args['path'] ?? '';
				$path = ABSPATH . ltrim( $rel, '/' );
				if ( ! file_exists( $path ) ) return new WP_REST_Response( array( 'error' => 'File not found' ), 404 );
				$lines = file( $path );
				$offset = (int) ( $args['offset'] ?? 0 );
				$limit = (int) ( $args['limit'] ?? 500 );
				return new WP_REST_Response( array( 'path' => $rel, 'total_lines' => count( $lines ), 'content' => implode( '', array_slice( $lines, $offset, $limit ) ) ), 200 );

			case 'file_write':
				$rel = $args['path'] ?? '';
				$content = $args['content'] ?? '';
				$apply = (bool) ( $args['apply'] ?? false );
				$path = ABSPATH . ltrim( $rel, '/' );
				$prev = file_exists( $path ) ? file_get_contents( $path ) : '';
				if ( $apply ) {
					wp_mkdir_p( dirname( $path ) );
					file_put_contents( $path, $content );
				}
				return new WP_REST_Response( array( 'path' => $rel, 'previous_content' => $prev, 'applied' => $apply ), 200 );

			case 'file_edit':
				$rel = $args['path'] ?? '';
				$target = $args['target'] ?? '';
				$repl = $args['replacement'] ?? '';
				$apply = (bool) ( $args['apply'] ?? false );
				$path = ABSPATH . ltrim( $rel, '/' );
				if ( ! file_exists( $path ) ) return new WP_REST_Response( array( 'error' => 'File not found' ), 404 );
				$prev = file_get_contents( $path );
				$count = substr_count( $prev, $target );
				if ( $apply ) {
					file_put_contents( $path, str_replace( $target, $repl, $prev ) );
				}
				return new WP_REST_Response( array( 'path' => $rel, 'match_count' => $count, 'previous_content' => $prev, 'applied' => $apply ), 200 );

			case 'file_tree':
				$rel = $args['directory'] ?? '';
				$dir = ABSPATH . ltrim( $rel, '/' );
				$max = (int) ( $args['max_depth'] ?? 3 );
				$items = array();
				$scan = function( $current, $depth ) use ( &$scan, &$items, $max ) {
					if ( $depth > $max || ! is_dir( $current ) ) return;
					$files = scandir( $current );
					foreach ( $files as $f ) {
						if ( $f === '.' || $f === '..' || $f[0] === '.' ) continue;
						$p = $current . '/' . $f;
						$items[] = str_replace( ABSPATH, '', $p );
						if ( is_dir( $p ) ) $scan( $p, $depth + 1 );
					}
				};
				$scan( rtrim( $dir, '/' ), 1 );
				return new WP_REST_Response( array( 'items' => $items, 'count' => count( $items ) ), 200 );

			case 'file_delete':
				$rel = $args['path'] ?? '';
				$apply = (bool) ( $args['apply'] ?? false );
				$path = ABSPATH . ltrim( $rel, '/' );
				$prev = file_exists( $path ) ? file_get_contents( $path ) : null;
				if ( $apply && file_exists( $path ) ) unlink( $path );
				return new WP_REST_Response( array( 'path' => $rel, 'previous_content' => $prev, 'applied' => $apply ), 200 );

			case 'snippet_save':
				$name = sanitize_title( $args['name'] ?? '' );
				$code = $args['code'] ?? '';
				$active = (bool) ( $args['active'] ?? true );
				$ext = $active ? '.php' : '.disabled';
				$dir = WPMU_PLUGIN_DIR . '/wpguard-snippets';
				wp_mkdir_p( $dir );
				$file = $dir . '/' . $name . $ext;
				$prev = file_exists( $file ) ? file_get_contents( $file ) : null;
				$full = "<?php\n/**\n * WPGuard Managed Snippet: {$name}\n */\n\n" . trim( $code );
				file_put_contents( $file, $full );
				return new WP_REST_Response( array( 'name' => $name, 'active' => $active, 'previous_content' => $prev, 'saved' => true ), 200 );

			case 'snippet_toggle':
				$name = sanitize_title( $args['name'] ?? '' );
				$active = (bool) ( $args['active'] ?? true );
				$dir = WPMU_PLUGIN_DIR . '/wpguard-snippets';
				$src = $dir . '/' . $name . ( $active ? '.disabled' : '.php' );
				$dst = $dir . '/' . $name . ( $active ? '.php' : '.disabled' );
				if ( file_exists( $src ) ) rename( $src, $dst );
				return new WP_REST_Response( array( 'name' => $name, 'active' => $active, 'toggled' => true ), 200 );

			case 'snippet_list':
				$dir = WPMU_PLUGIN_DIR . '/wpguard-snippets';
				$snippets = array();
				if ( is_dir( $dir ) ) {
					foreach ( scandir( $dir ) as $f ) {
						if ( $f === '.' || $f === '..' ) continue;
						$snippets[] = array( 'filename' => $f, 'active' => str_ends_with( $f, '.php' ) );
					}
				}
				return new WP_REST_Response( array( 'snippets' => $snippets ), 200 );

			case 'block_parse':
				return new WP_REST_Response( array( 'blocks' => parse_blocks( $args['content'] ?? '' ) ), 200 );

			case 'block_compose':
				return new WP_REST_Response( array( 'markup' => serialize_blocks( $args['blocks'] ?? array() ) ), 200 );

			case 'post_create':
				$post_data = array(
					'post_title'   => sanitize_text_field( $args['title'] ?? '' ),
					'post_content' => $args['content'] ?? '',
					'post_type'    => sanitize_text_field( $args['post_type'] ?? 'post' ),
					'post_status'  => sanitize_text_field( $args['status'] ?? 'draft' ),
					'meta_input'   => (array) ( $args['meta'] ?? array() ),
				);
				$pid = wp_insert_post( $post_data, true );
				if ( is_wp_error( $pid ) ) return new WP_REST_Response( array( 'error' => $pid->get_error_message() ), 400 );
				return new WP_REST_Response( array( 'post_id' => $pid, 'url' => get_permalink( $pid ) ), 200 );

			case 'magic_login':
				$u = get_user_by( 'login', $args['user_login'] ?? 'admin' ) ?: get_users( array( 'role' => 'administrator', 'number' => 1 ) )[0];
				$ttl = (int) ( $args['ttl_seconds'] ?? 600 );
				$token = wp_generate_password( 32, false );
				set_transient( 'wpguard_magic_' . hash( 'sha256', $token ), $u->ID, $ttl );
				$url = add_query_arg( array( 'wpguard_magic' => $token ), admin_url() );
				return new WP_REST_Response( array( 'login_url' => $url, 'user_id' => $u->ID, 'expires_in' => $ttl ), 200 );

			case 'skill_save':
				$skills = get_option( 'wpguard_skills', array() );
				$name = sanitize_title( $args['name'] ?? '' );
				$skills[ $name ] = array(
					'name'        => $name,
					'description' => sanitize_text_field( $args['description'] ?? '' ),
					'content'     => (string) ( $args['content'] ?? '' ),
					'updated_at'  => current_time( 'mysql', 1 ),
				);
				update_option( 'wpguard_skills', $skills, false );
				return new WP_REST_Response( array( 'saved' => true, 'name' => $name ), 200 );

			case 'skill_get':
				$skills = get_option( 'wpguard_skills', array() );
				$name = sanitize_title( $args['name'] ?? '' );
				return new WP_REST_Response( $skills[ $name ] ?? array( 'error' => 'Skill not found' ), 200 );

			case 'skill_list':
				$skills = get_option( 'wpguard_skills', array() );
				return new WP_REST_Response( array( 'skills' => array_values( $skills ) ), 200 );

			case 'design_context':
				$theme = wp_get_theme();
				$settings = function_exists( 'wp_get_global_settings' ) ? wp_get_global_settings() : array();
				$styles = function_exists( 'wp_get_global_styles' ) ? wp_get_global_styles() : array();
				return new WP_REST_Response( array(
					'theme'    => $theme->get( 'Name' ),
					'is_block' => wp_is_block_theme(),
					'colors'   => $settings['color']['palette']['theme'] ?? array(),
					'fonts'    => $settings['typography']['fontFamilies']['theme'] ?? array(),
					'styles'   => $styles,
				), 200 );

			case 'schema_recon':
				$pts = get_post_types( array( 'public' => true ), 'names' );
				$taxs = get_taxonomies( array( 'public' => true ), 'names' );
				$plugins = get_option( 'active_plugins', array() );
				$builders = array();
				foreach ( $plugins as $p ) {
					if ( stripos( $p, 'elementor' ) !== false ) $builders[] = 'Elementor';
					if ( stripos( $p, 'bricks' ) !== false ) $builders[] = 'Bricks';
					if ( stripos( $p, 'divi' ) !== false ) $builders[] = 'Divi';
					if ( stripos( $p, 'oxygen' ) !== false ) $builders[] = 'Oxygen';
					if ( stripos( $p, 'woocommerce' ) !== false ) $builders[] = 'WooCommerce';
					if ( stripos( $p, 'acf' ) !== false ) $builders[] = 'ACF';
				}
				return new WP_REST_Response( array(
					'post_types' => array_values( $pts ),
					'taxonomies' => array_values( $taxs ),
					'builders'   => array_values( array_unique( $builders ) ),
				), 200 );

			case 'db_query':
				global $wpdb;
				$sql = trim( $args['query'] ?? '' );
				$is_select = (bool) preg_match( '/^(SELECT|SHOW|DESCRIBE|EXPLAIN)\s/i', $sql );
				if ( $is_select ) {
					$rows = $wpdb->get_results( $sql, ARRAY_A );
					return new WP_REST_Response( array( 'rows' => $rows, 'count' => count( $rows ) ), 200 );
				}
				$apply = (bool) ( $args['apply'] ?? false );
				if ( ! $apply ) {
					return new WP_REST_Response( array( 'dry_run' => true, 'applied' => false, 'query' => $sql ), 200 );
				}
				$affected = $wpdb->query( $sql );
				return new WP_REST_Response( array( 'affected_rows' => $affected, 'applied' => true ), 200 );
		}
	} catch ( Exception $e ) {
		return new WP_REST_Response( array( 'error' => $e->getMessage() ), 500 );
	}

	return new WP_REST_Response( array( 'error' => 'Unhandled command' ), 500 );
}
