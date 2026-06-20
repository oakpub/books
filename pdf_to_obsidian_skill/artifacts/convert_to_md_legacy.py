import sys
import pymupdf4llm
import pathlib

sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)

PDF_PATH = "Рихтер Дж. - CLR via C#. Программирование на платформе Microsoft .NET Framework 4.5 на языке C#. 4-е изд. (Мастер-класс) - 2013.pdf"
OUTPUT_MD = "CLR_via_CSharp.md"
IMAGES_DIR = "images"

print("Converting PDF, please wait (this may take a few minutes)...")

md_text = pymupdf4llm.to_markdown(
    PDF_PATH,
    write_images=True,
    image_path=IMAGES_DIR,
    image_format="png",
    dpi=150,
)

pathlib.Path(OUTPUT_MD).write_bytes(md_text.encode("utf-8"))

print(f"\nDone!")
print(f"  Markdown: {OUTPUT_MD}")
print(f"  Images:   {IMAGES_DIR}/")
