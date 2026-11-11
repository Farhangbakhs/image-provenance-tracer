# ORIGIN eval report

Generated 2026-11-11 03:57Z by `make eval` in 271 s. Embedding model: `sscd_disc_mixup@9f26bd4`. Current thresholds: `v2`.

## Matching

18 source photographs (scikit-image sample data), each edited 14 ways a repost is edited, plus every ordered pair of different photographs as negatives. An edit counts as correct when the copy is classified related and in an acceptable class; a negative is correct when it is classified unrelated.

| Thresholds | Edited copies found (recall) | Right class | False positives on unrelated pairs |
| --- | --- | --- | --- |
| `v1` | 190/252 (75.4%) | 190/252 (75.4%) | 2/306 (0.7%) |
| `v2` | 236/252 (93.7%) | 236/252 (93.7%) | 2/306 (0.7%) |

### By edit (`v2`)

| Edit | What was done | Found | Right class | Median SSCD |
| --- | --- | --- | --- | --- |
| `resize` | scaled to 50% | 18/18 | 18/18 | 0.977 |
| `recompress` | JPEG quality 30 | 18/18 | 18/18 | 0.950 |
| `webp` | WebP quality 50 | 18/18 | 18/18 | 0.979 |
| `mirror` | mirrored | 17/18 | 17/18 | 0.954 |
| `rotate90` | rotated 90° | 17/18 | 17/18 | 0.703 |
| `grey` | converted to greyscale | 18/18 | 18/18 | 0.959 |
| `colour` | brightness +25%, contrast +30% | 18/18 | 18/18 | 0.977 |
| `crop80` | centre crop to 80% | 17/18 | 17/18 | 0.858 |
| `crop60` | off-centre crop to 60% | 16/18 | 16/18 | 0.660 |
| `caption` | cropped, with a caption bar | 17/18 | 17/18 | 0.757 |
| `watermark` | account watermark in a corner | 17/18 | 17/18 | 0.909 |
| `letterbox` | padded into a tall frame (screenshot) | 17/18 | 17/18 | 0.752 |
| `rotate5` | rotated 5° with expanded frame | 17/18 | 17/18 | 0.703 |
| `small_crop_caption` | scaled to 40%, cropped and captioned | 11/18 | 11/18 | 0.719 |

SSCD separation: the lowest score of an edited copy that was found is 0.522; unrelated pairs score at most 0.914 (99th percentile 0.243).

Hard negative (the same scene from a slightly different position):

- `motorcycle_left.png` vs `motorcycle_right.png`: near_duplicate (wrong); pHash 4 <= 8

### Edited copies not handled correctly (`v2`): 16

| Source | Edit | Got | Why |
| --- | --- | --- | --- |
| `chelsea.png` | `small_crop_caption` | unrelated | SSCD 0.710 < 0.75 and only 46 inliers |
| `rocket.jpg` | `small_crop_caption` | unrelated | SSCD 0.459 < 0.5 |
| `retina.jpg` | `crop60` | unrelated | SSCD 0.811 but no homography with >= 15 inliers |
| `retina.jpg` | `small_crop_caption` | unrelated | SSCD 0.821 but no homography with >= 15 inliers |
| `moon.png` | `small_crop_caption` | unrelated | SSCD 0.741 < 0.75 and only 24 inliers |
| `page.png` | `small_crop_caption` | unrelated | SSCD 0.487 < 0.5 |
| `text.png` | `small_crop_caption` | unrelated | SSCD 0.606 but no homography with >= 15 inliers |
| `clock_motion.png` | `mirror` | unrelated | SSCD 0.959 but no homography with >= 15 inliers |
| `clock_motion.png` | `rotate90` | unrelated | SSCD 0.617 but no homography with >= 15 inliers |
| `clock_motion.png` | `crop80` | unrelated | SSCD 0.879 but no homography with >= 15 inliers |
| `clock_motion.png` | `crop60` | unrelated | SSCD 0.742 but no homography with >= 15 inliers |
| `clock_motion.png` | `caption` | unrelated | SSCD 0.744 but no homography with >= 15 inliers |
| `clock_motion.png` | `watermark` | unrelated | SSCD 0.863 but no homography with >= 15 inliers |
| `clock_motion.png` | `letterbox` | unrelated | SSCD 0.722 but no homography with >= 15 inliers |
| `clock_motion.png` | `rotate5` | unrelated | SSCD 0.596 < 0.75 and only 15 inliers |
| `clock_motion.png` | `small_crop_caption` | unrelated | SSCD 0.610 but no homography with >= 15 inliers |

### False positives (`v2`): 2

- `motorcycle_left.png` vs `motorcycle_right.png`: near_duplicate; pHash 4 <= 8
- `motorcycle_right.png` vs `motorcycle_left.png`: near_duplicate; pHash 4 <= 8

## How to read this

- A false positive is worse than a miss: it would put an unrelated picture into the evidence. Thresholds are tuned to keep false positives at zero first, then raise recall.
- The sample photographs are small (mostly 512 px or less). Real reposts start from larger originals, so recall on heavy crops here is a floor, not a ceiling.
- Threshold files are never edited in place. A recalibration adds a new version, reruns this report, and every stored sighting keeps the version that classified it.
