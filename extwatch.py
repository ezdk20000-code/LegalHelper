# -*- coding: utf-8 -*-
"""
Слежение за файлами, открытыми в других программах (Word, Acrobat, Excel…).

Пользователь открывает документ дела в «родной» программе, правит и сохраняет — LegalHelper замечает, что
файл изменился, и обновляет его страницы у себя. Word сохраняет через временный файл и переименование,
поэтому вместо системных уведомлений файлы просто проверяются раз в полторы секунды (их немного — только
открытые во внешних программах). Изменение засчитывается, когда размер и время файла перестали меняться
(программа дописала файл до конца).
"""
import os

from PySide6.QtCore import QObject, QTimer, Signal


def _stamp(path):
    try:
        st = os.stat(path)
        return st.st_size, st.st_mtime
    except OSError:
        return None


class ExtWatch(QObject):
    changed = Signal(str)            # путь файла, который изменили и сохранили

    def __init__(self, parent=None, interval=1500):
        super().__init__(parent)
        self.files = {}              # норм. путь -> [путь, последняя учтённая отметка, кандидат]
        self.timer = QTimer(self)
        self.timer.setInterval(interval)
        self.timer.timeout.connect(self.poll)

    @staticmethod
    def _key(path):
        return os.path.normcase(os.path.abspath(path))

    def watch(self, path):
        self.files[self._key(path)] = [path, _stamp(path), None]
        self.timer.start()

    def unwatch(self, path):
        self.files.pop(self._key(path), None)
        if not self.files:
            self.timer.stop()

    def is_watched(self, path):
        return self._key(path) in self.files

    def refresh(self, path):
        """Файл записала сама программа — это не внешнее изменение."""
        f = self.files.get(self._key(path))
        if f:
            f[1], f[2] = _stamp(path), None

    def poll(self):
        for key, f in list(self.files.items()):
            path, known, cand = f
            now = _stamp(path)
            if now is None or now == known:          # нет файла (Word как раз переименовывает) или без изменений
                f[2] = None
                continue
            if cand != now:                          # ещё пишется — подождать следующей проверки
                f[2] = now
                continue
            f[1], f[2] = now, None
            self.changed.emit(path)
