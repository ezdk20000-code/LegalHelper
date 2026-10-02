# -*- coding: utf-8 -*-
"""
Лёгкие анимации интерфейса: заставка при запуске, плавное проявление содержимого при переходах,
выезжающие плашки. Эффект ставится только на время анимации (0,15–0,35 с) и сразу снимается, поэтому
в покое на компьютер ничего не нагружает. Встроенный браузер (карта дела) не анимируется — эффекты
прозрачности с ним несовместимы. Выключаются в «Вид → Анимации».
"""
from PySide6.QtCore import (Qt, QElapsedTimer, QEasingCurve, QPropertyAnimation, QParallelAnimationGroup, QTimer,
                            QEventLoop, QRectF, QPointF, QPoint, QVariantAnimation, QObject, QEvent)
from PySide6.QtGui import QPainter, QColor, QFont, QPixmap, QLinearGradient
from PySide6.QtWidgets import QWidget, QGraphicsOpacityEffect, QGraphicsDropShadowEffect, QApplication

ENABLED = True
_running = {}          # id(виджета) -> анимация (чтобы не наслаивать)


def _has_webview(w):
    import sys
    mod = sys.modules.get("PySide6.QtWebEngineWidgets")
    if mod is None:                 # встроенный браузер ещё не загружали — значит, его и нет на экране
        return False                # (не загружать его ради проверки: это 0,3 с на запуске)
    QWebEngineView = mod.QWebEngineView
    return isinstance(w, QWebEngineView) or w.findChild(QWebEngineView) is not None


def fade_in(w, ms=180):
    """Плавно проявить содержимое виджета (переход между вкладками, делами, разделами)."""
    if not ENABLED or w is None or not w.isVisible() or w.graphicsEffect() is not None or _has_webview(w):
        return
    eff = QGraphicsOpacityEffect(w)
    eff.setOpacity(0.0)
    w.setGraphicsEffect(eff)
    a = QPropertyAnimation(eff, b"opacity", w)
    a.setDuration(ms)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setEasingCurve(QEasingCurve.OutCubic)

    def done():
        _running.pop(id(w), None)
        if w.graphicsEffect() is eff:
            w.setGraphicsEffect(None)
    a.finished.connect(done)
    _running[id(w)] = a
    a.start(QPropertyAnimation.DeleteWhenStopped)


def slide_in(w, dx=0, dy=14, ms=240):
    """Переход: содержимое проявляется и чуть «подъезжает» на место (снизу или сбоку), как в современных
    программах. Сдвиг небольшой (10–20 точек), длится четверть секунды."""
    if not ENABLED or w is None or not w.isVisible() or w.graphicsEffect() is not None or _has_webview(w):
        return
    old = _running.pop(id(w), None)
    if old is not None:
        try:
            old.stop()
        except RuntimeError:
            pass
    end = w.pos()
    eff = QGraphicsOpacityEffect(w)
    eff.setOpacity(0.0)
    w.setGraphicsEffect(eff)
    grp = QParallelAnimationGroup(w)
    fa = QPropertyAnimation(eff, b"opacity", grp)
    fa.setDuration(ms)
    fa.setStartValue(0.0)
    fa.setEndValue(1.0)
    fa.setEasingCurve(QEasingCurve.OutCubic)
    ma = QPropertyAnimation(w, b"pos", grp)
    ma.setDuration(ms)
    ma.setStartValue(end + QPoint(dx, dy))
    ma.setEndValue(end)
    ma.setEasingCurve(QEasingCurve.OutCubic)
    grp.addAnimation(fa)
    grp.addAnimation(ma)

    def done():
        _running.pop(id(w), None)
        try:
            if w.graphicsEffect() is eff:
                w.setGraphicsEffect(None)
            if w.pos() != end:
                w.move(end)
        except RuntimeError:
            pass
    grp.finished.connect(done)
    _running[id(w)] = grp
    grp.start(QParallelAnimationGroup.DeleteWhenStopped)


def pop_in(win, dy=10, ms=200):
    """Окно (диалог, меню) появляется мягко: проявляется и слегка «всплывает» на место."""
    if not ENABLED or win is None:
        return
    end = win.pos()
    win.setWindowOpacity(0.0)
    grp = QParallelAnimationGroup(win)
    fa = QPropertyAnimation(win, b"windowOpacity", grp)
    fa.setDuration(ms)
    fa.setStartValue(0.0)
    fa.setEndValue(1.0)
    fa.setEasingCurve(QEasingCurve.OutCubic)
    grp.addAnimation(fa)
    if dy:
        ma = QPropertyAnimation(win, b"pos", grp)
        ma.setDuration(ms)
        ma.setStartValue(end + QPoint(0, dy))
        ma.setEndValue(end)
        ma.setEasingCurve(QEasingCurve.OutCubic)
        grp.addAnimation(ma)

    def done():
        _running.pop(id(win), None)
        try:
            win.setWindowOpacity(1.0)
        except RuntimeError:
            pass
    grp.finished.connect(done)
    _running[id(win)] = grp
    grp.start(QParallelAnimationGroup.DeleteWhenStopped)
    # страховка: окно ни при каких условиях не остаётся прозрачным
    QTimer.singleShot(ms + 400, lambda: _safe_opaque(win))


def _safe_opaque(win):
    try:
        if win.windowOpacity() < 1.0 and id(win) not in _running:
            win.setWindowOpacity(1.0)
    except RuntimeError:
        pass


def slide_down(w, ms=240):
    """Показать плашку, «выезжая» сверху (анимация высоты)."""
    if not ENABLED:
        w.show()
        return
    w.setMaximumHeight(0)
    w.show()
    target = max(w.sizeHint().height(), 30)
    a = QPropertyAnimation(w, b"maximumHeight", w)
    a.setDuration(ms)
    a.setStartValue(0)
    a.setEndValue(target)
    a.setEasingCurve(QEasingCurve.OutCubic)
    a.finished.connect(lambda: w.setMaximumHeight(16777215))
    _running[id(w)] = a
    a.start(QPropertyAnimation.DeleteWhenStopped)


def window_fade(win, start=0.0, end=1.0, ms=220, then=None):
    """Проявить / скрыть окно целиком (прозрачность окна — это делает сама Windows, почти бесплатно)."""
    if not ENABLED:
        win.setWindowOpacity(end)
        if then:
            then()
        return None
    win.setWindowOpacity(start)
    a = QPropertyAnimation(win, b"windowOpacity", win)
    a.setDuration(ms)
    a.setStartValue(start)
    a.setEndValue(end)
    a.setEasingCurve(QEasingCurve.OutCubic if end > start else QEasingCurve.InCubic)
    if then:
        a.finished.connect(then)
    _running[id(win)] = a
    a.finished.connect(lambda: _running.pop(id(win), None))
    a.start(QPropertyAnimation.DeleteWhenStopped)
    return a


def wait(ms):
    """Дать анимации поиграть, не блокируя окно (используется только при запуске)."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class Splash(QWidget):
    """Заставка при запуске: иконка, название и бегущая полоска, пока открывается главное окно."""

    def __init__(self, pixmap, name, version, dark=False):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(360, 250)
        self.name, self.version, self.dark = name, version, dark
        self.pix = pixmap if isinstance(pixmap, QPixmap) else QPixmap(pixmap)
        self.phase = 0.0
        self.progress = 0.0            # полоска заполняется слева направо, а не «бегает»
        self.held = False
        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        scr = QApplication.primaryScreen()
        if scr:
            g = scr.availableGeometry()
            self.move(g.center().x() - self.width() // 2, g.center().y() - self.height() // 2)

    def _tick(self):
        t = min(1.0, self.clock.elapsed() / 220.0)
        self.phase = t
        self.progress = 0.9 * (1 - (1 - t) ** 3)          # плавное замедление к концу
        self.update()

    def start(self):
        self.clock.start()
        self.show()
        self.timer.start()
        window_fade(self, 0.0, 1.0, 260)
        QApplication.processEvents()

    def hold(self):
        """Замереть перед тяжёлой работой (сборка главного окна): неподвижная картинка не выглядит
        «подвисшей», а бегущая полоска, остановившаяся на полпути, — выглядит."""
        self.timer.stop()
        self.progress, self.phase = 0.9, 1.0
        self.held = True
        self.repaint()
        QApplication.processEvents()

    def finish(self, main_window):
        """Главное окно сначала полностью отрисовывается (ещё невидимым), потом проявляется, а заставка тает."""
        self.timer.stop()
        self.progress = 1.0
        self.repaint()
        QApplication.processEvents()
        main_window.repaint()
        QApplication.processEvents()
        window_fade(main_window, 0.0, 1.0, 280)
        window_fade(self, self.windowOpacity(), 0.0, 220, then=self.close)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        bg, fg, sub = (("#1c1c1e", "#f2f2f7", "#98989f") if self.dark else ("#ffffff", "#1c1c1e", "#8e8e93"))
        for i in range(6, 0, -1):                         # мягкая тень
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 5))
            p.drawRoundedRect(r.adjusted(-i, -i + 3, i, i + 3), 22 + i, 22 + i)
        p.setBrush(QColor(bg))
        p.drawRoundedRect(r, 22, 22)
        # иконка с лёгким «дыханием»
        s = 80 + 8 * (1 - (1 - self.phase) ** 3)            # иконка мягко «вырастает» при появлении
        if not self.pix.isNull():
            p.drawPixmap(QRectF(r.center().x() - s / 2, r.top() + 30 + (88 - s) / 2, s, s), self.pix,
                         QRectF(self.pix.rect()))
        f = QFont(self.font())
        f.setPointSize(17)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(fg))
        p.drawText(QRectF(r.left(), r.top() + 126, r.width(), 32), Qt.AlignCenter, self.name)
        f.setPointSize(9)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(sub))
        p.drawText(QRectF(r.left(), r.top() + 156, r.width(), 20), Qt.AlignCenter, f"версия {self.version}")
        # полоска загрузки
        track = QRectF(r.center().x() - 70, r.bottom() - 36, 140, 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(118, 118, 128, 50))
        p.drawRoundedRect(track, 2, 2)
        if self.progress > 0:
            seg = QRectF(track.left(), track.top(), track.width() * self.progress, 4)
            grad = QLinearGradient(QPointF(seg.left(), 0), QPointF(seg.right(), 0))
            grad.setColorAt(0, QColor(0, 122, 255, 140))
            grad.setColorAt(1, QColor(0, 122, 255, 255))
            p.setBrush(grad)
            p.drawRoundedRect(seg, 2, 2)
        p.end()


def count_up(label, start, end, render, ms=650):
    """Число «отсчитывается» от прежнего значения до нового (карточки на Главной)."""
    cur = _running.get(id(label))
    if cur is not None and getattr(cur, "_target", None) == end:
        return                                   # уже отсчитывает к этому же числу — не сбивать
    old = _running.pop(id(label), None)
    if not ENABLED or start == end or not label.isVisible():
        if old is not None:
            try:
                old.stop()
            except RuntimeError:
                pass
        label.setText(render(end))
        return
    if old is not None:
        try:
            old.stop()
        except RuntimeError:
            pass
    a = QVariantAnimation(label)
    a._target = end
    a.setDuration(ms)
    a.setStartValue(float(start))
    a.setEndValue(float(end))
    a.setEasingCurve(QEasingCurve.OutCubic)
    a.valueChanged.connect(lambda v: label.setText(render(int(round(v)))))

    def done():
        label.setText(render(end))
        if _running.get(id(label)) is a:
            _running.pop(id(label), None)
    a.finished.connect(done)
    _running[id(label)] = a
    a.start(QVariantAnimation.DeleteWhenStopped)


class _Lift(QObject):
    """Карточка при наведении мягко «приподнимается»: под ней вырастает тень."""

    def __init__(self, w, color):
        super().__init__(w)
        self.w, self.color, self.anim = w, color, None

    def eventFilter(self, o, e):
        t = e.type()
        if t == QEvent.Enter:
            self._go(22, 6)
        elif t == QEvent.Leave:
            self._go(0, 0)
        return False

    def _go(self, blur, dy):
        if not ENABLED:
            return
        w = self.w
        eff = w.graphicsEffect()
        if not isinstance(eff, QGraphicsDropShadowEffect):
            if eff is not None or blur == 0:
                return
            eff = QGraphicsDropShadowEffect(w)
            eff.setColor(self.color)
            eff.setBlurRadius(0)
            eff.setOffset(0, 0)
            w.setGraphicsEffect(eff)
        if self.anim is not None:
            try:
                self.anim.stop()
            except RuntimeError:
                pass
        a = QVariantAnimation(self)
        a.setDuration(180)
        a.setStartValue(float(eff.blurRadius()))
        a.setEndValue(float(blur))
        a.setEasingCurve(QEasingCurve.OutCubic)
        k = dy / blur if blur else (eff.yOffset() / eff.blurRadius() if eff.blurRadius() else 0)

        def step(v):
            try:
                eff.setBlurRadius(v)
                eff.setOffset(0, v * (k if k else 6 / 22))
            except RuntimeError:
                pass

        def done():
            if blur == 0:
                try:
                    if w.graphicsEffect() is eff:
                        w.setGraphicsEffect(None)        # в покое — без эффекта, ничего не нагружает
                except RuntimeError:
                    pass
        a.valueChanged.connect(step)
        a.finished.connect(done)
        self.anim = a
        a.start(QVariantAnimation.DeleteWhenStopped)


def hover_lift(w, color=None):
    from PySide6.QtGui import QColor as _C
    f = _Lift(w, color or _C(0, 0, 0, 60))
    w.installEventFilter(f)
    return f


class Toast(QWidget):
    """Короткое сообщение внизу рабочей области: выезжает снизу и проявляется, потом тает.
    У «✓ Сохранено…» галочка рисуется на глазах — понятно, что действие удалось."""

    def __init__(self, host, text, bg, fg, accent, ms=2600):
        super().__init__(host)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.success = text.lstrip().startswith("✓")
        self.text = text.lstrip()[1:].strip() if self.success else text
        self.bg, self.fg, self.accent = QColor(bg), QColor(fg), QColor(accent)
        self.check = 0.0 if (self.success and ENABLED) else 1.0
        f = QFont(self.font())
        f.setBold(True)
        self.setFont(f)
        fm = self.fontMetrics()
        maxw = max(200, host.width() - 40)
        icon = 30 if self.success else 0
        from PySide6.QtCore import QRect
        tw = min(fm.horizontalAdvance(self.text) + 2, maxw - 36 - icon)
        th = fm.boundingRect(QRect(0, 0, tw, 10000), Qt.TextWordWrap, self.text).height()
        h = max(40, th + 20)
        self.resize(tw + 36 + icon, h)
        self.move(max(10, (host.width() - self.width()) // 2), max(10, host.height() - h - 28))
        self.show()
        self.raise_()
        slide_in(self, dx=0, dy=18, ms=260)
        if self.success and ENABLED:
            a = QVariantAnimation(self)
            a.setDuration(420)
            a.setStartValue(0.0)
            a.setEndValue(1.0)
            a.setEasingCurve(QEasingCurve.OutCubic)
            a.valueChanged.connect(self._set_check)
            QTimer.singleShot(140, lambda: a.start(QVariantAnimation.DeleteWhenStopped))
        QTimer.singleShot(ms, self.dismiss)

    def _set_check(self, v):
        self.check = v
        self.update()

    def dismiss(self):
        try:
            if not ENABLED:
                self.deleteLater()
                return
            eff = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(eff)
            a = QPropertyAnimation(eff, b"opacity", self)
            a.setDuration(220)
            a.setStartValue(1.0)
            a.setEndValue(0.0)
            a.finished.connect(self.deleteLater)
            a.start(QPropertyAnimation.DeleteWhenStopped)
        except RuntimeError:
            pass

    def paintEvent(self, _e):
        from PySide6.QtGui import QPen, QPainterPath
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(self.bg)
        p.drawRoundedRect(r, 12, 12)
        x = 18
        if self.success:
            c = QRectF(14, r.center().y() - 11, 22, 22)
            p.setBrush(QColor("#34c759"))
            p.drawEllipse(c)
            path = QPainterPath()
            pts = [QPointF(c.left() + 6, c.center().y() + 0.5), QPointF(c.left() + 9.5, c.center().y() + 4),
                   QPointF(c.right() - 5.5, c.center().y() - 4)]
            t = self.check
            path.moveTo(pts[0])
            if t <= 0.4:                                     # первая черта галочки, потом вторая
                path.lineTo(pts[0] + (pts[1] - pts[0]) * (t / 0.4))
            else:
                path.lineTo(pts[1])
                path.lineTo(pts[1] + (pts[2] - pts[1]) * ((t - 0.4) / 0.6))
            pen = QPen(QColor("#ffffff"), 2.4)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            if t > 0:
                p.drawPath(path)
            x = 44
        p.setPen(self.fg)
        p.drawText(QRectF(x, 0, r.width() - x - 16, r.height()), Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap,
                   self.text)
        p.end()
