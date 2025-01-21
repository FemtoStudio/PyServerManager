from PySide6 import QtCore, QtGui, QtWidgets


class CollapsibleHeader(QtWidgets.QWidget):
    clicked = QtCore.Signal()

    def __init__(self, text, parent=None):
        super(CollapsibleHeader, self).__init__(parent)

        self._expanded = False

        # Instead of referencing custom image resources, use standard Qt icons
        self.COLLAPSED_ICON = self.style().standardIcon(QtWidgets.QStyle.SP_ArrowRight)
        self.EXPANDED_ICON  = self.style().standardIcon(QtWidgets.QStyle.SP_ArrowDown)

        self.setAutoFillBackground(True)
        self.set_background_color(None)

        # Enable mouse tracking/hover events
        self.setAttribute(QtCore.Qt.WA_Hover, True)

        # Icon label
        self.icon_label = QtWidgets.QLabel()
        # Pick an icon size for your arrow. Here we use 16×16, adjust as you like:
        icon_size = 16
        self.icon_label.setFixedSize(icon_size, icon_size)

        # Text label
        self.text_label = QtWidgets.QLabel()
        self.text_label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)

        # Layout
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.main_layout.setContentsMargins(4, 4, 4, 4)
        self.main_layout.setSpacing(6)

        self.main_layout.addWidget(self.icon_label)
        self.main_layout.addWidget(self.text_label)

        self.set_text(text)
        self.set_expanded(False)

        # Store default palette for hover effect
        self._default_palette = self.palette()

    def set_text(self, text):
        self.text_label.setText("<b>{0}</b>".format(text))

    def set_background_color(self, color):
        if not color:
            color = QtWidgets.QPushButton().palette().color(QtGui.QPalette.Button)

        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, color)
        self.setPalette(palette)

    def set_header_text_color(self, color):
        """
        Set the text color of the header label.
        """
        palette = self.text_label.palette()
        palette.setColor(QtGui.QPalette.WindowText, color)
        self.text_label.setPalette(palette)

    def is_expanded(self):
        return self._expanded

    def set_expanded(self, expanded):
        self._expanded = expanded

        # Convert the QIcon to a QPixmap of desired size
        icon_size = self.icon_label.size()
        if expanded:
            pixmap = self.EXPANDED_ICON.pixmap(icon_size)
        else:
            pixmap = self.COLLAPSED_ICON.pixmap(icon_size)

        self.icon_label.setPixmap(pixmap)

    def mouseReleaseEvent(self, event):
        super(CollapsibleHeader, self).mouseReleaseEvent(event)
        self.clicked.emit()  # pylint: disable=E1101

    def enterEvent(self, event):
        """
        Simple hover style: Lighten the background slightly.
        """
        super(CollapsibleHeader, self).enterEvent(event)
        highlight_palette = self.palette()
        base_color = highlight_palette.color(QtGui.QPalette.Window)
        # Make the color slightly lighter on hover
        lighter_color = base_color.lighter(110)
        highlight_palette.setColor(QtGui.QPalette.Window, lighter_color)
        self.setPalette(highlight_palette)

    def leaveEvent(self, event):
        """
        Revert to the default background color on hover leave.
        """
        super(CollapsibleHeader, self).leaveEvent(event)
        self.setPalette(self._default_palette)


class CollapsibleFrame(QtWidgets.QWidget):
    def __init__(self, text, parent=None, animation_duration=200):
        """
        :param text: Header text
        :param parent: Parent widget
        :param animation_duration: Time in ms for expand/collapse animation
        """
        super(CollapsibleFrame, self).__init__(parent)

        self.animation_duration = animation_duration
        self._use_animation = True
        self._animation = None

        # Header widget
        self.header_wdg = CollapsibleHeader(text)
        self.header_wdg.clicked.connect(self.on_header_clicked)

        # Body widget
        self.body_wdg = QtWidgets.QGroupBox()
        self.body_layout = QtWidgets.QVBoxLayout(self.body_wdg)
        self.body_layout.setContentsMargins(4, 2, 4, 2)
        self.body_layout.setSpacing(3)

        # Main layout
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.main_layout.addWidget(self.header_wdg)
        self.main_layout.addWidget(self.body_wdg)

        self.set_expanded(True)

    def add_widget(self, widget):
        self.body_layout.addWidget(widget)

    def add_layout(self, layout):
        self.body_layout.addLayout(layout)

    def set_expanded(self, expanded):
        """
        Expands or collapses the frame. Uses animation if enabled.
        """
        # If no change, do nothing
        if expanded == self.header_wdg.is_expanded():
            return

        self.header_wdg.set_expanded(expanded)

        if self._use_animation:
            self._toggle_animation(expanded)
        else:
            self.body_wdg.setVisible(expanded)

    def set_header_background_color(self, color):
        self.header_wdg.set_background_color(color)

    def set_header_text_color(self, color):
        self.header_wdg.set_header_text_color(color)

    def enable_animation(self, enable=True):
        """
        Enable or disable expand/collapse animations.
        """
        self._use_animation = enable

    def on_header_clicked(self):
        self.set_expanded(not self.header_wdg.is_expanded())

    def _toggle_animation(self, expand):
        """
        Create and start a QPropertyAnimation to animate the height of
        the group box.
        """
        start_value = self.body_wdg.maximumHeight()
        if start_value <= 0:
            # If the widget is hidden, we need to set a plausible start height
            start_value = 0

        if expand:
            # Make the body visible so sizeHint() is computed properly
            self.body_wdg.setVisible(True)
            self.body_wdg.adjustSize()
            end_value = self.body_wdg.sizeHint().height()
        else:
            end_value = 0

        # Create or reuse the animation
        if self._animation:
            self._animation.stop()

        self._animation = QtCore.QPropertyAnimation(self.body_wdg, b"maximumHeight")
        self._animation.setDuration(self.animation_duration)
        self._animation.setStartValue(start_value)
        self._animation.setEndValue(end_value)
        self._animation.setEasingCurve(QtCore.QEasingCurve.InOutCubic)
        self._animation.finished.connect(lambda: self._on_animation_finished(expand))
        self._animation.start()

    def _on_animation_finished(self, expand):
        """
        Hide the widget if animation ended in a collapsed state.
        """
        if not expand:
            self.body_wdg.setVisible(False)
        # Reset the max height so layout is unconstrained
        self.body_wdg.setMaximumHeight(16777215)

