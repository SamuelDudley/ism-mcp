# Security policy

ism-mcp is a local, single-tenant tool. It serves over stdio with no network listener and no authentication, and is intended for local and per-project use rather than multi-tenant or networked deployment. It reads the ISM database and project-local coverage manifests; it does not transmit data anywhere.

## Reporting a vulnerability

Report suspected vulnerabilities privately. Open a [GitHub security advisory](https://github.com/samueldudley/ism-mcp/security/advisories/new) or email dudley.samuel@gmail.com. Please do not open a public issue for a security report.

Include the affected version or commit, reproduction steps, and the impact you observed. Expect an acknowledgement within about a week.
