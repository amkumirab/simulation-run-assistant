# Security Policy

## Supported versions

This project is currently an early-stage MVP. Security fixes are applied to the
latest version on the default branch.

## Reporting a vulnerability

Do not open a public issue for a vulnerability or exposed credential. Use
GitHub's private vulnerability reporting feature when it is enabled for the
repository. If private reporting is unavailable, contact the repository owner
privately through their GitHub profile.

Include the affected version, reproduction steps, impact, and any suggested
mitigation. Please allow reasonable time for investigation before public
disclosure.

## Deployment warning

The interactive dashboard only accepts loopback bindings and protects write
requests with a random, in-memory session token. This is a local safety boundary,
not user authentication. Do not proxy or expose the dashboard to an untrusted
network without a proper authentication and transport-security layer.
