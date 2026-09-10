# Public marketing site

`site/` contains the existing static website at https://wpmcpserver.com/.
It was imported from its authoritative deployment on 2026-09-09:
`prod-77:/var/www/kaibuilds/sites/wpmcpserver`.

Caddy serves that directory directly. `wpmcp.io` redirects to the same site.
There is no GitHub Pages deployment. Updating Git does not deploy these files.

Keep existing routes, shared styles, page metadata, `index.md`, `llms.txt`,
`og.svg`, and `sitemap.xml` consistent. Review rendered desktop and mobile
pages before deployment. Back up the existing remote files before replacing
them and read the published pages back afterward.

Install links point to the source installation guide. Cloud offers describe
arranged early access: new organizations cannot enroll in a trial or purchase
through online checkout. Existing users can sign in at
https://app.wpmcp.io/sign-in. Preserve published pricing unless separately
authorized to change it.

Only public product material belongs here. Client histories, imported
corrections, private reports and runtime state must never enter this directory.
Use explicitly illustrative examples rather than customer records.
