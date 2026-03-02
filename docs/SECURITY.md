# Security

## Secrets handling

- **Never commit secrets.** Do not add `.env`, tokens, API keys, or webhook secrets to the repository. Use `.env.example` as a template with placeholders only.
- **Where to store secrets:** Local use `.env` (git-ignored). CI use GitHub Secrets or your platform’s secret store. Production use a secrets manager (e.g. Azure Key Vault) and inject as environment variables.
- **Guardrails:** The agent must not log or output secrets. See [GUARDRAILS.md](GUARDRAILS.md) for rules (redaction, least privilege, no exfiltration).

## Reporting vulnerabilities

If you find a security issue, report it privately to the maintainers (e.g. via private channel or security policy) rather than opening a public issue.

## Disclaimer

This project provides a baseline and documentation for secure configuration. You are responsible for applying your organization’s security policies and for securing any deployment (credentials, network, and data).
