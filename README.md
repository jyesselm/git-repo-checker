# git-repo-checker

Scan and report status of git repositories.

## Installation

```bash
pip install -e ".[dev]"
```

## Usage

```bash
# Initialize a config file
grc init

# Scan repositories
grc scan

# Check a single repo
grc check /path/to/repo
```

## Configuration

Copy `config.example.yml` to `~/.config/git-repo-checker/config.yml` or `./git-repo-checker.yml`.
