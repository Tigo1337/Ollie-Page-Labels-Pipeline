# Test fixtures

`scm_letter_v6_marks.pdf` is the registration-mark reference for `tests/test_template_match.py`.
It is made from `Starter_15-22_portrait.pdf`, a card-proxy page printed and cut successfully with
silhouette-card-maker's `letter-standard-v6` template on the Cameo 5. Only SCM's own 600 ppi
pixels around the three Type 1 marks are kept; the card art is removed (it was 21 MB and plays no
part in the check). The page keeps the original box and rotation: MediaBox 792 × 612 pt, /Rotate 270.

The tests check that our marks land where SCM's do (within 0.2 mm; only the arm length differs,
10 mm vs 8.04 mm) and that both PDFs print with the square at the bottom left.
