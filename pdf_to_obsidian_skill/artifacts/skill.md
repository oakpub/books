# Skill: Universal PDF to Obsidian Vault Conversion

This skill defines the standard operating procedure for converting any text-based PDF (books, manuals, textbooks, documentation) into a structured Obsidian vault.

## Prerequisites
- The python script `d:\p\PyMuPDF4LLM\pdf_to_obsidian_skill\artifacts\pdf_to_obsidian.py` must exist.
- The `pymupdf4llm` package must be installed in the environment.

## Trigger
When the user asks to "convert this PDF to Obsidian", "parse this book into a vault", or similar requests involving extracting a PDF.

## Execution Steps

### 1. Analyze the Request & Document
Before running the script, you must determine the appropriate parameters. If the user hasn't provided this information, you can briefly inspect the PDF (e.g., using `pymupdf4llm` to read the first few pages) or ask the user:
- **Domain:** What is the subject matter? (e.g., programming, mathematics, history, fiction)
- **Primary Language (if code is present):** What is the main programming language? (e.g., python, javascript, csharp, text). Use `text` if it's a non-technical document.
- **Tags:** What tags should be applied to the notes? (e.g., book, textbook, python, machine_learning)
- **Structure:** Usually `auto` is fine, but you can specify `chapters`, `sections`, or `flat`.

**IMPORTANT:** If the document's domain or primary code language is completely ambiguous, use the `ask_question` tool to clarify with the user.

### 2. Invoke the Universal Script
Run the `pdf_to_obsidian.py` script with the determined parameters.

```bash
python "d:\p\PyMuPDF4LLM\pdf_to_obsidian_skill\artifacts\pdf_to_obsidian.py" "path\to\document.pdf" --domain <domain> --lang <language> --tags <tag1,tag2>
```

Example for a Python programming book:
```bash
python "d:\p\PyMuPDF4LLM\pdf_to_obsidian_skill\artifacts\pdf_to_obsidian.py" "C:\books\FluentPython.pdf" --domain programming --lang python --tags "book,python,programming"
```

Example for a history book:
```bash
python "d:\p\PyMuPDF4LLM\pdf_to_obsidian_skill\artifacts\pdf_to_obsidian.py" "C:\books\HistoryOfRome.pdf" --domain history --lang text --tags "book,history,rome"
```

### 3. Verify the Output
After the script completes, briefly verify the output:
- Ensure the output directory was created (default is `<pdf_name>_Obsidian`).
- Check that markdown files were generated.
- If the script reports errors (e.g., missing dependencies), resolve them and re-run.

### 4. Present to User
Inform the user that the conversion is complete, summarize the number of chapters/files generated, and provide the path to the resulting Obsidian vault.
