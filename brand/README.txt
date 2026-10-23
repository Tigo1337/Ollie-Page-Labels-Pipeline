Mazie Page Creations - logo files

SVG files are the masters (text converted to outlines; no fonts needed).
PNG files are transparent exports; the number is the width in pixels.

mazie-page-logo-horizontal        primary logo (mark + word mark)
mazie-page-logo-horizontal-white  for Plum / dark backgrounds
mazie-page-logo-stacked           mark above the word mark
mazie-page-mark                   the little page on its own (logo mark)
mazie-page-mark-plum / -white     one-colour marks (stamps, embossing, dark backgrounds)
mazie-page-wordmark(-white/-short) word mark only ("short" = without CREATIONS)
mazie-page-icon(-lilac/-plum)     square icon: Etsy shop icon (500 px), avatars, favicon (32 px)

icons/                            the 4 icons of the "Made to last" image (waterproof, peel, heart,
                                  Québec fleur-de-lis), SVG + 256 px PNG

Colours: Plum #3E2352, Lilac #C9B5F0, Blush #F5BFD0, Pearl #FBF7FB
         (a deeper tone of Blush, #EFA3BF, is used only for the heart and the cheeks)
Fonts:   Fredoka SemiBold (titles, word mark), Nunito (text) - both free (OFL)

build_logo.py rebuilds every file from Fredoka:
  python3 build_logo.py "Fredoka[wdth,wght].ttf" out
