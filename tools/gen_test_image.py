#!/usr/bin/env python3
# Generate a strongly asymmetric test image for the Nowa-213R-N EPD.
# The panel storage buffer is 250x128 (16 bytes/column), but the physical glass
# only exposes about 250x122 rows; the bottom ~6 rows are off-screen.
# This test image is drawn for the VISIBLE 250x122 area so the border touches
# all four edges of the actual glass.
# Used to verify: (a) image shows at all, (b) orientation is correct (not
# mirrored), (c) full screen coverage with no clipping / black band.
# White background, black ink (matches the panel's 0x00=black / 0xFF=white).
import os
from PIL import Image, ImageDraw

W, VISIBLE_H = 250, 122
img = Image.new('L', (W, VISIBLE_H), 255)   # white background
d = ImageDraw.Draw(img)

# 1) 3px black border (verifies full-screen coverage on the visible glass)
d.rectangle([0, 0, W - 1, VISIBLE_H - 1], outline=0, width=3)

# 2) Top-LEFT 24x24 solid black square -> orientation marker (should appear top-left)
d.rectangle([6, 6, 29, 29], fill=0)

# 3) Big RIGHT-pointing arrow in the middle (should point right; flipped => points left)
y = VISIBLE_H // 2
d.line([40, y, 200, y], fill=0, width=8)            # shaft
d.polygon([(200, y - 18), (200, y + 18), (224, y)], fill=0)  # arrow head at right

# 4) Bottom horizontal bar with a GAP on the LEFT, just above the visible bottom edge
bottom = VISIBLE_H - 8
d.rectangle([60, bottom - 8, 244, bottom], fill=0)   # bar from x=60..244 (gap 0..59)

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_image.png')
img.save(out)
print('wrote', out, img.size)
