# Security policy

FS-SC writes files and runs verification commands on your machine, so security reports matter.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private reporting: **Security → Report a vulnerability** on the repository page. Include what you found, how to reproduce it and the commit.

## Notes

- The server binds to `127.0.0.1` by default and is meant for local use.
- Verification commands pass a deny-list, and a secret scan blocks commits that contain keys or assigned passwords.
- The test profiles bundled for E2E demos use placeholder credentials for local fixtures only.
