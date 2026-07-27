# qCoder Release Version Policy

Published qCoder versions are immutable. Distinct wheel or source-distribution bytes require a
distinct version identity, and no private build may reuse a version that is already published on
PyPI.

Every private release build must be traceable to its repository, branch, exact commit, and complete
SHA-256 artifact hashes. The package version must agree across `pyproject.toml`,
`qcoder.__version__`, built wheel metadata, built source-distribution metadata, and the
customer-facing package pins included in the release unit.

Release proof must record the source commit, wheel hash, source-distribution hash, and publication
source. Private artifacts that reuse a published version are obsolete and must be either moved to a
clearly marked non-installable quarantine or recorded as absent. The official published artifact
must not be altered, renamed, moved, or quarantined.
