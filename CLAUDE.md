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
- Оформление (iOS-стиль) — `THEMES` и `make_style()` в `pdf_master.py`; мелочи, не задаваемые стилями, — `polish_ui()`.
- Снимки для справки: `QT_QPA_PLATFORM=offscreen python tools/screenshots.py help/img` (светлая тема) и
  `... tools/screenshots.py /tmp/dark dark` → `01_main.png` скопировать в `help/img/23_dark.png`.
- Сохранность: `backup.py` (резервные копии, проверка базы), `casefile.py` (папка дела + LegalHelper-дело.json).
  Миграции базы — только добавлением колонок (`CaseDB._migrate`), чтобы откат на старую версию не ломал данные.
- Пользователь может пропускать версии: `version.json` → `notes` пишем так, чтобы было понятно и тем, кто обновляется
  через несколько версий.
