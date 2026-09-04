#!/usr/bin/env python3
# Generate a strongly asymmetric test image for the Nowa-213R-N EPD (250x128).
# Used to verify: (a) image shows at all, (b) orientation is correct (not
# mirrored), (c) full screen coverage with no clipping / black band.
# White background, black ink (matches the panel's 0x00=black / 0xFF=white).
import os
from PIL import Image, ImageDraw

W, H = 250, 128
img = Image.new('L', (W, H), 255)   # white background
d = ImageDraw.Draw(img)

# 1) 3px black border (verifies full-screen coverage, no clipping)
d.rectangle([0, 0, W - 1, H - 1], outline=0, width=3)

# 2) Top-LEFT 24x24 solid black square -> orientation marker (should appear top-left)
d.rectangle([6, 6, 29, 29], fill=0)

# 3) Big RIGHT-pointing arrow in the middle (should point right; flipped => points left)
y = 64
d.line([40, y, 200, y], fill=0, width=8)            # shaft
d.polygon([(200, y - 18), (200, y + 18), (224, y)], fill=0)  # arrow head at right

# 4) Bottom horizontal bar with a GAP on the LEFT (strongly asymmetric)
d.rectangle([60, 112, 244, 120], fill=0)            # bar from x=60..244 (gap 0..59)

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_image.png')
img.save(out)
print('wrote', out, img.size)
