# Security Policy

## Supported Versions

Currently supported versions of HyperTrade:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1   | :x:                |

---

## Reporting a Vulnerability

**Do not report security vulnerabilities through public GitHub issues.**

### Reporting Process

If you discover a security vulnerability in HyperTrade, please report it privately:

1. **Email**: Contact the repository owner directly (see repository settings)
2. **Include**:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if available)

### Response Timeline

- **Initial Response**: Within 48 hours
- **Status Update**: Within 5 business days
- **Fix Timeline**: Depends on severity (see below)

### Severity Levels

| Severity | Description | Fix Timeline |
|----------|-------------|--------------|
| **Critical** | Remote code execution, data breach, unauthorized access to production systems | 24-48 hours |
| **High** | Privilege escalation, authentication bypass, significant data exposure | 3-7 days |
| **Medium** | Information disclosure, DoS, limited privilege escalation | 14-30 days |
| **Low** | Minor information leaks, non-exploitable vulnerabilities | 30-60 days |

---

## Security Measures

### Current Protections

**Authentication & Authorization**:
- Session-based authentication for privileged operations
- HttpOnly, SameSite cookies with secure flag in production
- Admin-only routes for write operations and control actions
- Time-limited sessions

**Data Protection**:
- Secrets stored in environment variables, never in code
- Database credentials isolated per environment
- API keys and tokens stored securely
- No sensitive data in logs or trace events

**API Security**:
- Input validation on all endpoints
- SQL injection protection via SQLAlchemy ORM
- CORS restrictions to allowed origins
- Rate limiting (planned)

**BitPro Integration**:
- Only access through stable MCP/API contracts
- Never bypass BitPro risk boundaries
- Read-only diagnostics for live operations
- Explicit preflight checks before operations

**Execution Safety**:
- Approval gates for Testnet orders
- Risk policy enforcement before tool execution
- Idempotency keys for write operations
- Mainnet execution blocked in V1

**Infrastructure**:
- Docker container isolation
- Network segmentation (Nginx reverse proxy)
- Minimal container privileges
- Regular security updates

### Known Limitations

**V1 Scope**:
- Mainnet live order execution is intentionally blocked
- No rate limiting on API endpoints (planned for V2)
- Single admin user (multi-user auth planned)
- Session management is basic (no refresh tokens)

**Development Environment**:
- SQLite mode for development only (PostgreSQL recommended for production)
- Development server runs without HTTPS (production uses Nginx TLS)
- Debug logs may contain sensitive information (disable in production)

---

## Security Best Practices

### For Operators

**Secrets Management**:
- Never commit `.env` files to version control
- Use strong, unique passwords for admin accounts
- Rotate API keys regularly
- Store production secrets securely (environment variables, secrets manager)

**Access Control**:
- Limit access to production servers
- Use SSH keys instead of passwords
- Enable firewall rules to restrict access
- Monitor access logs regularly

**Deployment**:
- Use HTTPS in production (Nginx with TLS certificates)
- Keep Docker images and system packages updated
- Review deployment logs for anomalies
- Enable audit logging for privileged operations

### For Developers

**Code Security**:
- Never hardcode secrets or credentials
- Validate all user inputs
- Use parameterized queries (avoid string interpolation)
- Handle exceptions securely (don't expose stack traces to users)
- Review dependencies for known vulnerabilities

**Testing**:
- Include security test cases
- Test authentication and authorization logic
- Verify input validation
- Check for SQL injection and XSS vulnerabilities

**Dependencies**:
- Keep dependencies up-to-date
- Review security advisories for Python and npm packages
- Use lock files (`uv.lock`, `pnpm-lock.yaml`) for reproducible builds
- Audit dependencies regularly

---

## Vulnerability Disclosure Policy

### Our Commitment

- We take all security reports seriously
- We will acknowledge receipt within 48 hours
- We will provide regular updates on progress
- We will publicly disclose vulnerabilities after fixes are deployed

### Public Disclosure

After a vulnerability is fixed:

1. **Fix Deployed**: Security patch released and deployed to production
2. **Grace Period**: 7 days for users to update (if applicable)
3. **Public Disclosure**: Vulnerability details published in:
   - CHANGELOG.md
   - Security advisories (if GitHub repository is public)
   - Release notes

### Recognition

We will credit security researchers who responsibly disclose vulnerabilities:
- Acknowledgment in release notes
- Credit in security advisories
- Optional public recognition (if researcher agrees)

---

## Security Checklist

### Production Deployment

- [ ] `.env` file has restricted permissions (600)
- [ ] Database credentials are strong and unique
- [ ] Nginx is configured with TLS certificates
- [ ] Firewall rules restrict access to necessary ports
- [ ] Docker containers run with minimal privileges
- [ ] Secrets are not committed to version control
- [ ] Admin password is strong and not default
- [ ] SSH access is key-based only
- [ ] System packages are up-to-date
- [ ] Application logs are monitored

### Code Review

- [ ] No hardcoded secrets or credentials
- [ ] Input validation on all endpoints
- [ ] SQL queries use parameterized statements
- [ ] Error messages don't expose sensitive information
- [ ] Authentication checks on privileged routes
- [ ] CORS settings are restrictive
- [ ] Dependencies are up-to-date
- [ ] Security tests pass

---

## Incident Response

### In Case of Security Incident

1. **Contain**: Isolate affected systems immediately
2. **Assess**: Determine scope and impact
3. **Notify**: Inform repository owner and affected parties
4. **Remediate**: Apply fixes and patches
5. **Review**: Post-mortem analysis and documentation
6. **Improve**: Update security measures to prevent recurrence

### Emergency Contacts

- **Repository Owner**: See repository settings
- **Production Server**: SSH access with emergency key
- **Database**: Backup and restore procedures in runbooks

---

## Security Resources

### External References

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [CWE/SANS Top 25](https://cwe.mitre.org/top25/)
- [Python Security Best Practices](https://python.readthedocs.io/en/stable/library/security_warnings.html)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [Node.js Security Best Practices](https://nodejs.org/en/docs/guides/security/)

### Internal Documentation

- [Deployment Guide](docs/deployment.md)
- [Incident Response Runbook](docs/runbooks/incident-response.md)
- [Architecture - Security](docs/architecture/)

---

## Updates to This Policy

This security policy may be updated periodically. Check the commit history for changes.

**Last Updated**: 2026-07-05

---

## Responsible Disclosure

We appreciate security researchers who:
- Follow responsible disclosure practices
- Provide detailed reports
- Allow reasonable time for fixes
- Don't exploit vulnerabilities for malicious purposes

Thank you for helping keep HyperTrade and its users safe! 🔒
