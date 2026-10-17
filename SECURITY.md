# Security Policy

## Status

Agent Mandate is an early-stage, personal project. It uses only synthetic data and must not be connected to real mailboxes, accounts or credentials. There are no supported production releases.

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's "Report a vulnerability" feature on this repository (Security tab), rather than a public issue. Include the affected component, steps to reproduce, and the impact you expect. You can expect an acknowledgement within a reasonable time; this is a one-person project, so there is no formal service level.

## Scope

In scope: authorisation bypass in the check logic, impersonation across agents or tenants, injection through ids or text, secret exposure, and anything that lets an agent grant itself authority.

Out of scope: stopping prompt injection in general (the project controls authority, not model behaviour), compromise of the host or database, and issues that need access to the admin key. See [docs/security-privacy.md](docs/security-privacy.md) for the threat model.

## Secrets

Never commit API keys. `.env` is git-ignored; `.env.example` lists variable names only. If a key is committed by mistake, rotate it immediately and remove it from history.
