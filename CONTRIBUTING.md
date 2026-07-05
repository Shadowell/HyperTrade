# Contributing to HyperTrade

Thank you for your interest in contributing to HyperTrade! This document provides guidelines and instructions for contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Documentation](#documentation)
- [Submitting Changes](#submitting-changes)
- [Review Process](#review-process)

---

## Code of Conduct

This project adheres to a code of conduct. By participating, you are expected to uphold this code. Please report unacceptable behavior to the project maintainers.

### Our Standards

**Positive behaviors**:
- Using welcoming and inclusive language
- Being respectful of differing viewpoints and experiences
- Gracefully accepting constructive criticism
- Focusing on what is best for the community
- Showing empathy towards other community members

**Unacceptable behaviors**:
- Trolling, insulting/derogatory comments, and personal or political attacks
- Public or private harassment
- Publishing others' private information without explicit permission
- Other conduct which could reasonably be considered inappropriate in a professional setting

---

## Getting Started

### Prerequisites

- Python 3.12+
- `uv` package manager
- Node.js 18+ and `pnpm`
- Git
- Docker and Docker Compose (optional, for PostgreSQL)

### Setting Up Development Environment

1. **Fork and Clone**:
   ```bash
   git clone git@github.com:YOUR_USERNAME/HyperTrade.git
   cd HyperTrade
   ```

2. **Set Up Python Environment**:
   ```bash
   uv sync
   ```

3. **Set Up Frontend**:
   ```bash
   npm exec --yes pnpm@10 -- -C frontend install
   ```

4. **Configure Environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your API keys and configuration
   ```

5. **Initialize Database**:
   ```bash
   # For SQLite (quickstart)
   mkdir -p .local
   export DATABASE_URL="sqlite:///$(pwd)/.local/hypertrade.db"

   # For PostgreSQL (recommended for development)
   docker compose up -d postgres
   export DATABASE_URL="postgresql://hypertrade:hypertrade@localhost:5432/hypertrade"
   uv run alembic upgrade head
   ```

6. **Verify Setup**:
   ```bash
   ./scripts/check.sh
   ```

---

## Development Workflow

### Branch Strategy

**Current workflow**: Direct commits to `main` branch.

For future contributions:
- Create a feature branch from `main`: `git checkout -b feature/your-feature-name`
- Use descriptive branch names: `feature/`, `bugfix/`, `docs/`, `refactor/`

### Sprint Contracts

HyperTrade development is organized by sprint contracts in `docs/contracts/`.

**Before starting work**:
1. Check `docs/contracts/` for the active sprint scope
2. Review related architecture docs in `docs/architecture/`
3. Understand the acceptance criteria and boundaries

**During development**:
- Keep changes within the current sprint contract unless explicitly expanded
- Update architecture docs when introducing new patterns or components
- Add eval cases to guard against regressions

### Making Changes

1. **Create a Branch** (future workflow):
   ```bash
   git checkout -b feature/add-new-tool
   ```

2. **Make Your Changes**:
   - Write clean, readable code
   - Follow the coding standards (see below)
   - Add tests for new functionality
   - Update documentation

3. **Test Your Changes**:
   ```bash
   ./scripts/check.sh
   ```

4. **Commit Your Changes**:
   ```bash
   git add .
   git commit -m "Add new market intelligence tool"
   ```

   **Commit message format**:
   ```
   Brief summary (50 chars or less)

   More detailed explanatory text, if necessary. Wrap it to
   about 72 characters. The blank line separating the summary
   from the body is critical.

   - Bullet points are okay
   - Use present tense: "Add feature" not "Added feature"
   - Reference issues: "Fixes #123" or "Related to #456"
   ```

---

## Coding Standards

### Python

**Style**:
- Follow PEP 8
- Use type hints for function signatures
- Maximum line length: 100 characters

**Formatting**:
```bash
uv run ruff format .
```

**Linting**:
```bash
uv run ruff check .
```

**Type Checking**:
```bash
uv run mypy backend/src
```

**Example**:
```python
from typing import Any

def get_market_ticker(
    symbol: str,
    include_funding: bool = True,
) -> dict[str, Any]:
    """Get market ticker for a symbol.
    
    Args:
        symbol: Symbol name (e.g., "BTC", "ETH")
        include_funding: Include funding rate data
        
    Returns:
        Ticker data dictionary
    """
    # Implementation
    pass
```

### TypeScript/React

**Style**:
- Use TypeScript for all new code
- Follow ESLint rules
- Use functional components with hooks

**Linting**:
```bash
npm exec --yes pnpm@10 -- -C frontend lint
```

**Example**:
```typescript
interface MarketTickerProps {
  symbol: string;
  onUpdate?: (data: TickerData) => void;
}

export function MarketTicker({ symbol, onUpdate }: MarketTickerProps) {
  const [data, setData] = useState<TickerData | null>(null);
  
  useEffect(() => {
    // Implementation
  }, [symbol]);
  
  return (
    <div className="market-ticker">
      {/* Component JSX */}
    </div>
  );
}
```

### Documentation

**Code Comments**:
- Write self-documenting code with clear variable and function names
- Add comments only when code cannot express intent clearly
- Document complex algorithms or business logic
- Keep comments up-to-date with code changes

**Docstrings**:
- Use docstrings for all public functions, classes, and modules
- Follow Google style for Python docstrings
- Include type information and examples when helpful

---

## Testing

### Running Tests

**Full Test Suite**:
```bash
./scripts/check.sh
```

**Backend Tests**:
```bash
uv run pytest tests/ -v
```

**Frontend Tests**:
```bash
npm exec --yes pnpm@10 -- -C frontend test
```

**Specific Test**:
```bash
uv run pytest tests/test_agent_eval_suite.py::test_eval_tool_choice -v
```

**With Coverage**:
```bash
uv run pytest --cov=hypertrade --cov-report=html
```

### Writing Tests

**Test Structure**:
- Place tests in `tests/` directory
- Name test files `test_*.py`
- Name test functions `test_*`
- Use descriptive test names that explain the scenario

**Example Test**:
```python
def test_market_ticker_returns_valid_data():
    """Test that market ticker returns valid ticker data."""
    repo = MarketRepository(db)
    ticker = repo.get_ticker("BTC-USDT-SWAP")
    
    assert ticker is not None
    assert ticker.inst_id == "BTC-USDT-SWAP"
    assert ticker.last > 0
    assert ticker.volume_ccy_24h >= 0
```

### Evaluation Cases

Add eval cases to `AgentEvalSuite` to guard against regressions:

```python
def _eval_my_new_feature(self) -> EvalResult:
    """Test my new feature behavior."""
    kernel = AgentKernel(self.db, "docs/knowledge", self.settings)
    run = kernel.run_chat("Test prompt for my feature")
    
    assert run.status == "completed"
    assert "expected_tool" in [t["tool"] for t in run.trace]
    
    return EvalResult(
        eval_id="my_new_feature",
        status="pass",
        message="Feature works correctly"
    )
```

---

## Documentation

### When to Document

**Always document**:
- New tools, providers, or connectors
- API changes or new endpoints
- Architecture decisions
- Configuration changes
- Operational procedures

**Don't document**:
- Implementation details visible in code
- Temporary workarounds
- Debug notes or chat history

### Documentation Types

**Architecture Docs** (`docs/architecture/`):
- Module-level design decisions
- Component interactions
- Technical patterns

**Knowledge Base** (`docs/knowledge/`):
- Operator guides
- Best practices
- Tool usage examples

**Runbooks** (`docs/runbooks/`):
- Deployment procedures
- Troubleshooting guides
- Incident response

**Contracts** (`docs/contracts/`):
- Sprint scope and deliverables
- Acceptance criteria
- Technical specifications

### Documentation Standards

- Write in clear, concise English or Chinese
- Use markdown formatting
- Include code examples where helpful
- Keep docs up-to-date with code changes
- Link related documentation

---

## Submitting Changes

### Before Submitting

- [ ] Code follows project style guidelines
- [ ] All tests pass (`./scripts/check.sh`)
- [ ] New tests added for new functionality
- [ ] Documentation updated
- [ ] Eval cases added if needed
- [ ] Commit messages are clear and descriptive

### Submission Process

**Current workflow** (direct to main):
1. Ensure your changes are committed
2. Push to `origin/main`
3. Automatic deployment via GitHub Actions

**Future workflow** (with PRs):
1. Push your branch to your fork
2. Create a Pull Request against `main`
3. Fill out the PR template
4. Wait for review and address feedback
5. Once approved, changes will be merged

### Pull Request Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] All tests pass
- [ ] New tests added
- [ ] Manually tested

## Checklist
- [ ] Code follows style guidelines
- [ ] Documentation updated
- [ ] No breaking changes (or documented)
- [ ] Sprint contract scope respected

## Related Issues
Fixes #123
Related to #456
```

---

## Review Process

### Review Criteria

**Code Quality**:
- Follows project conventions
- Clear and maintainable
- Properly tested
- No unnecessary complexity

**Functionality**:
- Meets requirements
- Handles edge cases
- No regressions
- Within sprint scope

**Documentation**:
- Architecture docs updated
- API changes documented
- Usage examples provided

### Response Time

- Reviews typically within 1-2 business days
- Address feedback promptly
- Be patient and respectful

### After Approval

- Changes will be merged to `main`
- Automatic deployment to production
- Monitor deployment logs
- Verify production health

---

## Getting Help

### Resources

- **Documentation**: [docs/documentation-index.md](docs/documentation-index.md)
- **Architecture**: [docs/architecture/](docs/architecture/)
- **Developer Guide**: [docs/developer-guide.md](docs/developer-guide.md)

### Communication

- **Issues**: Use GitHub Issues for bugs and feature requests
- **Discussions**: Use GitHub Discussions for questions
- **Email**: Contact maintainers for sensitive issues

---

## License

By contributing to HyperTrade, you agree that your contributions will be licensed under the same license as the project.

---

## Recognition

Contributors will be recognized in:
- Release notes
- CHANGELOG.md
- Project README (if significant contribution)

Thank you for contributing to HyperTrade! 🎉
