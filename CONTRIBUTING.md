# Contributing to RHDS Migration with Ansible

Thank you for your interest in contributing to this project! This document provides guidelines and information for contributors.

## Code of Conduct

This project follows a code of conduct to ensure a welcoming environment for all contributors.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/your-username/dirsrv-migrate.git`
3. Create a feature branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Run tests and linting
6. Submit a pull request

## Development Environment

### Prerequisites

- Python 3.11+
- Ansible core
- Podman (for local testing)
- ruff, ansible-lint, yamllint (for linting)

### Setup

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install Ansible collections
ansible-galaxy collection install -r collections/requirements.yml

# For local testing with Podman
make up_389ds
make init_389ds
```

## Code Style and Standards

This project follows the guidelines outlined in `AGENTS.md`. Key requirements:

### YAML/Ansible
- Use 2-space indentation
- Use FQCN (Fully Qualified Collection Names) for all modules
- Prefer `ansible.builtin.*` modules
- Set `changed_when` and `failed_when` appropriately for idempotence
- Use `no_log: true` for sensitive operations

### Python
- Follow PEP 8 style guidelines
- Use ruff for linting and formatting
- Add type hints where appropriate

### Git Commits
- Use Conventional Commits format:
  - `feat:` for new features
  - `fix:` for bug fixes
  - `docs:` for documentation
  - `refactor:` for code refactoring
  - `test:` for test-related changes
  - `chore:` for maintenance

## Testing

### Local Testing

```bash
# Syntax check
ansible-playbook --syntax-check site.yml

# Dry run
ansible-playbook --check --diff site.yml -i inventory.yml

# Local Podman testing
make test_389ds
make test_repl_mesh
```

### Test Categories

- **Unit tests**: Individual role/component testing
- **Integration tests**: Full workflow testing with Podman
- **Idempotence tests**: Ensure playbooks can run multiple times safely

## Pull Request Process

1. Ensure your branch is up to date with `main`
2. Run all tests and linting locally
3. Update documentation if needed
4. Create a pull request with:
   - Clear description of changes
   - Reference to any related issues
   - Test results or validation steps
   - Screenshots/logs if applicable

### PR Checklist

- [ ] Code follows style guidelines
- [ ] Tests pass locally
- [ ] Documentation updated
- [ ] Commit messages follow conventional format
- [ ] No sensitive data committed
- [ ] CI checks pass

## Security Considerations

- Never commit secrets or sensitive data
- Use Ansible Vault for sensitive variables
- Set `no_log: true` on tasks handling passwords
- Review code for potential security issues before committing

## Areas for Contribution

- Bug fixes and improvements
- Documentation enhancements
- Test coverage improvements
- Performance optimizations
- New features (coordinate with maintainers first)

## Getting Help

- Check existing issues and documentation
- Open a discussion for questions
- Contact maintainers for guidance

## License

By contributing to this project, you agree that your contributions will be licensed under the Apache License 2.0.
