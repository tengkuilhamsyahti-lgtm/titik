"""Titik masuk untuk PyInstaller.

PyInstaller butuh satu skrip biasa sebagai titik masuk; ia tidak bisa
membungkus `python -m titik` secara langsung.
"""

import multiprocessing
import sys

from titik.__main__ import main

if __name__ == "__main__":
    # Wajib ada sebelum apa pun yang lain di Windows: tanpa ini, setiap
    # proses anak akan menjalankan ulang seluruh program.
    multiprocessing.freeze_support()
    sys.exit(main())
