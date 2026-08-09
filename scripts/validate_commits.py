#!/usr/bin/env python3
"""Validate commit messages in a PR range against Conventional Commits format.

Usage:
    python validate_commits.py <base_ref> <head_ref> [--allow-merge-commits]

Example:
    python validate_commits.py main HEAD --allow-merge-commits
"""

import argparse
import re
import subprocess
import sys

ALLOWED_TYPES = [
    "feat",
    "fix",
    "docs",
    "style",
    "refactor",
    "perf",
    "test",
    "build",
    "ci",
    "chore",
    "revert",
    "initial",  # legacy: first commit of the project used this type
]

# Conventional Commits pattern: <type>(scope): <description> or <type>: <description> (min 10 chars)

COMMIT_PATTERN = re.compile(r"^(?P<type>" + "|".join(ALLOWED_TYPES) + r")(\([a-z0-9_-]+\))?: (?P<desc>.{10,})$")


def get_commits(base_ref: str, head_ref: str):
    """Get list of commit hashes between base and head refs."""
    try:
        result = subprocess.run(
            ["git", "log", "--format=%H %s", f"{base_ref}..{head_ref}", "--no-merges"],
            check=True,
            capture_output=True,
            text=True,
        )
        return [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to get commits between {base_ref} and {head_ref}")
        print(e.stderr)
        sys.exit(1)


def validate_commit(commit_line: str, allow_merge_commits: bool = False):
    """Validate a single commit message.

    Returns (is_valid, error_message).
    Merge commits are skipped when allow_merge_commits is True.
    """
    # Format from git log --format="%H %s" is "<hash> <subject>"
    parts = commit_line.split(" ", 1)
    if len(parts) != 2:
        return False, f"Invalid commit format (no subject found): {commit_line}"

    _sha, message = parts

    # Skip merge commits when allowed
    if allow_merge_commits and "Merge " in message:
        print(f"SKIP (merge commit): {message[:80]}")
        return True, None

    # Skip revert commits (squash-merge reverts use Revert "..." format)
    if allow_merge_commits and re.match(r'^Revert "', message):
        print(f"SKIP (revert commit): {message[:80]}")
        return True, None

    # Skip squash-merge commits: GitHub uses PR title as commit msg ending with (#N),
    # but only skip if it doesn't already match conventional commits format
    if allow_merge_commits and re.search(r"\(\#\d+\)$", message) and not COMMIT_PATTERN.match(message):
        print(f"SKIP (squash merge commit): {message[:80]}")
        return True, None

    # Accept legacy first-commit messages from the original project
    if re.match(r"^Initial commit$", message):
        print(f"SKIP (legacy initial commit): {message}")
        return True, None

    match = COMMIT_PATTERN.match(message)
    if not match:
        types_str = ", ".join(ALLOWED_TYPES)
        error_msg = (
            f"{_sha}: '{message}'\n"
            f"  -> Must follow format: <type>(scope): <description> or <type>: <description> (min 10 chars)\n"
            f"  Allowed types: {types_str}"
        )
        return False, error_msg

    print(f"OK   {_sha[:8]}: {message}")
    return True, None


def main():
    parser = argparse.ArgumentParser(description="Validate Conventional Commits format")
    parser.add_argument("base_ref", help="Base ref to start checking from (e.g., main)")
    parser.add_argument("head_ref", help="Head ref to end at (e.g., HEAD or branch name)")
    parser.add_argument("--allow-merge-commits", action="store_true", help="Skip merge commits")
    args = parser.parse_args()

    base_ref = args.base_ref
    head_ref = args.head_ref
    allow_merge_commits = args.allow_merge_commits

    print(f"Validating commits from {base_ref}..{head_ref}")
    print("=" * 65)

    commit_lines = get_commits(base_ref, head_ref)

    if not commit_lines:
        print("No non-merge commits found to validate.")
        sys.exit(0)

    errors = []
    for line in commit_lines:
        is_valid, error_msg = validate_commit(line, allow_merge_commits)
        if not is_valid and error_msg:
            errors.append(error_msg)

    print("=" * 65)

    if errors:
        print(f"\n❌ {len(errors)} commit(s) violated Conventional Commits format:\n")
        for err in errors:
            print(err + "\n")
        sys.exit(1)

    print(f"✅ All {len(commit_lines)} commits follow Conventional Commits.")
    sys.exit(0)


if __name__ == "__main__":
    main()
