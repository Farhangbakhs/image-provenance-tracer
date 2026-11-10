# C2PA trust list

`C2PA-TRUST-LIST.pem` is the official C2PA trust list: X.509 trust anchors for certificate authorities that issue signing certificates to conforming generator products.

| | |
| --- | --- |
| Source | https://github.com/c2pa-org/conformance-public/blob/64b3f9c8ebb95d2b73557aea25172d694db67c1e/trust-list/C2PA-TRUST-LIST.pem |
| Commit | `64b3f9c8ebb95d2b73557aea25172d694db67c1e` (2026-11-04) |
| Anchors | 33 |
| SHA-256 | `148c1c167e98dc909a0d5793d2feee1022aa60fef5c83a0d6b08f67f4446bc37` |
| Licence | CC-BY-4.0, © C2PA (Coalition for Content Provenance and Authenticity) |

The file is pinned so that a trust decision is reproducible: every asset records which list it was checked against. `origin_core.ingest.c2pa` verifies the SHA-256 above when it loads the file and refuses to run on a mismatch.

To update: download the PEM from a new commit of `c2pa-org/conformance-public`, then update the commit, date, anchor count and hash here and the `TRUST_LIST_*` constants in `origin_core/ingest/c2pa.py`.
