# LegalHelper

Настольная программа для Windows (Python 3.12+, PySide6, PyMuPDF), собирается PyInstaller'ом через `update.bat`.
Владелец — не программист: объяснять по-русски и простыми словами.

- Точка входа — `pdf_master.py`; юридические функции — `legal_ui.py` / `legal_core.py`, дела — `cases.py`, `case_tabs.py`,
  справка — `help_ui.py`, обновления с GitHub — `updater.py`.
- `.bat` и `.iss` хранятся с CRLF — при правке сохранять переводы строк (см. `.gitattributes`).
- Папки с данными пользователя (`%LOCALAPPDATA%\PDFMaster`, `PDFMaster-build`) остались от старого названия — не переименовывать.
- **`main` — выпущенная версия**: установленные программы читают `version.json` из `main` и скачивают архив `main`.
  Выпуск: поднять `APP_VERSION` (pdf_master.py), `MyAppVersion` (installer.iss), `version.json` (версия + notes),
  дописать `CHANGELOG.md`, затем влить в `main`.
