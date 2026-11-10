# C2PA test fixtures

From the c2pa-python repository at tag `v0.38.0` (`tests/fixtures/`), MIT / Apache-2.0.

| File | Upstream name | Use |
| --- | --- | --- |
| `no-manifest.jpg` | `A.jpg` | An image with no Content Credentials: state `none`. |
| `signed-test-cert.jpg` | `C.jpg` | Signed by the "C2PA Test Signing Cert", which is not on the trust list: state `present_untrusted`, with a validated, trusted timestamp. |
| `test-es256-chain.pem` | `es256_certs.pem` | Public test signing chain (leaf and root). |
| `test-es256-private.key` | `es256_private.key` | The matching **published test key**. It is not a secret and signs nothing real. |

The tests sign `no-manifest.jpg` with the test chain at run time to produce a `valid_trusted` image (with the chain's root added as a trust anchor) and a tampered copy (state `present_untrusted`, validation state `Invalid`).
