"""Main application window.

Sidebar on the left with network list and connection settings.
Content area on the right that shows the network canvas or unit detail view.
Status bar at the bottom with connection info.
"""

import time
import uuid
import importlib
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QFileSystemWatcher
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QStackedWidget,
    QFrame, QListWidget, QListWidgetItem, QStatusBar,
    QDialog, QDialogButtonBox, QFormLayout, QMessageBox,
    QSplitter, QSizePolicy, QTextEdit,
)

from environnets.core import PioAPI, add_log_listener
from environnets.core.config import get
from environnets.core.models import Store, Network, Unit, Connection
from environnets.core.experiments import (
    Experiment, save_experiment, list_experiments,
    load_experiment, delete_experiment,
)
from environnets.ui.theme import (
    STYLESHEET, ACCENT, ACCENT_DIM, GREEN, RED, TEXT_PRIMARY,
    TEXT_SECONDARY, TEXT_MUTED, BG_CARD, BG_PANEL, BG_HOVER, BG_INPUT,
    BORDER, BORDER_HOVER,
)
from environnets.ui.canvas import NetworkCanvas
from environnets.ui.experiment_panel import ExperimentPanel
from environnets.ui.connection_dialog import ConnectionDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EnvironNets")
        self.setStyleSheet(STYLESHEET)

        # Core state
        self.store = Store()
        default_url = get("connection", "default_url", "http://localhost")
        self.api = PioAPI(self.store.get_setting("pioreactor_url", default_url))
        self.connected = False
        self.current_network: Network | None = None

        self._build_ui()
        self._load_networks()

        # Connection check timer
        poll_ms = get("connection", "poll_interval_seconds", 10) * 1000
        self._conn_timer = QTimer(self)
        self._conn_timer.timeout.connect(self._check_connection)
        self._conn_timer.start(poll_ms)

        self._ping_timer = QTimer(self)
        self._ping_timer.timeout.connect(self._ping_linked_units)
        self._ping_timer.start(8000)
        self._check_connection()

        # API log listener
        add_log_listener(self._on_api_log)

        # Hot reload: watch source files for changes
        self._watcher = QFileSystemWatcher(self)
        src_dir = Path(__file__).resolve().parent
        watch_files = [str(f) for f in src_dir.rglob("*.py")]
        core_dir = src_dir.parent / "core"
        watch_files += [str(f) for f in core_dir.rglob("*.py")]
        self._watcher.addPaths(watch_files)
        self._watcher.fileChanged.connect(self._on_source_changed)

        # Ctrl+R manual reload
        from PyQt6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Ctrl+R"), self, self._hot_reload)

    # -- UI construction ---------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Sidebar (resizable so small MacBook screens can give space to the canvas)
        sidebar = self._sidebar = self._build_sidebar()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(188)
        sidebar.setMaximumWidth(360)
        sidebar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        self.content_stack = QStackedWidget()
        self.content_stack.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._build_welcome_page()
        self._build_canvas_page()

        # Logger panel (collapsible)
        self._log_panel = QFrame()
        self._log_panel.setVisible(False)
        self._log_panel.setFixedHeight(160)
        self._log_panel.setStyleSheet(
            f"QFrame{{background:{BG_CARD};border-top:1px solid {BORDER}}}"
        )
        log_vl = QVBoxLayout(self._log_panel)
        log_vl.setContentsMargins(8, 4, 8, 4)
        log_vl.setSpacing(2)
        log_hdr = QHBoxLayout()
        log_title = QLabel("API Log")
        log_title.setStyleSheet(f"font-size:10px;font-weight:600;color:{TEXT_SECONDARY}")
        log_hdr.addWidget(log_title)
        log_hdr.addStretch()
        log_clear = QPushButton("Clear")
        log_clear.setFixedSize(48, 20)
        log_clear.setStyleSheet(f"font-size:9px;padding:0;border-radius:3px")
        log_clear.clicked.connect(lambda: self._log_text.clear())
        log_hdr.addWidget(log_clear)
        log_vl.addLayout(log_hdr)
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setStyleSheet(
            f"QTextEdit{{background:{BG_INPUT};border:1px solid {BORDER};"
            f"border-radius:4px;font-family:monospace;font-size:10px;color:{TEXT_SECONDARY}}}"
        )
        log_vl.addWidget(self._log_text)

        content_col = QWidget()
        content_vl = QVBoxLayout(content_col)
        content_vl.setContentsMargins(0, 0, 0, 0)
        content_vl.setSpacing(0)
        content_vl.addWidget(self.content_stack, 1)
        content_vl.addWidget(self._log_panel)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(5)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(sidebar)
        splitter.addWidget(content_col)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([252, 980])
        layout.addWidget(splitter)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._conn_dot = QLabel()
        self._conn_label = QLabel("Checking connection...")
        self._log_btn = QPushButton("Log")
        self._log_btn.setFixedSize(40, 20)
        self._log_btn.setStyleSheet(
            f"QPushButton{{font-size:9px;padding:0;border-radius:3px;"
            f"border:1px solid {BORDER};background:{BG_CARD};color:{TEXT_MUTED}}}"
            f"QPushButton:hover{{color:{TEXT_PRIMARY};background:{BG_HOVER}}}"
        )
        self._log_btn.clicked.connect(self._toggle_log)
        self.status_bar.addWidget(self._conn_dot)
        self.status_bar.addWidget(self._conn_label)
        self.status_bar.addPermanentWidget(self._log_btn)

    def _build_sidebar(self) -> QFrame:
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(12)

        # App title
        title = QLabel("EnvironNets")
        title.setStyleSheet(f"font-size: 18px; font-weight: 600; color: {TEXT_PRIMARY}; margin-bottom: 2px; letter-spacing: 0.5px;")
        layout.addWidget(title)

        subtitle = QLabel("Bioreactor networks")
        subtitle.setStyleSheet(f"font-size: 11px; color: {TEXT_MUTED}; margin-bottom: 12px;")
        layout.addWidget(subtitle)

        # Connection button
        self._conn_btn = QPushButton("Configure connection")
        self._conn_btn.clicked.connect(self._open_connection_dialog)
        layout.addWidget(self._conn_btn)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {BORDER};")
        layout.addWidget(sep)

        # Networks section
        net_header = QHBoxLayout()
        net_label = QLabel("Networks")
        net_label.setStyleSheet("font-size: 14px; font-weight: 500;")
        net_add_btn = QPushButton("+")
        net_add_btn.setFixedSize(26, 26)
        net_add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {TEXT_MUTED};
                border: 1px solid {BORDER};
                border-radius: 6px;
                font-size: 15px;
                font-weight: 500;
                padding: 0;
            }}
            QPushButton:hover {{ color: {TEXT_PRIMARY}; border-color: {BORDER_HOVER}; background: {BG_HOVER}; }}
        """)
        net_add_btn.clicked.connect(self._create_network_dialog)
        net_header.addWidget(net_label)
        net_header.addStretch()
        net_header.addWidget(net_add_btn)
        layout.addLayout(net_header)

        # Network list
        self.network_list = QListWidget()
        self.network_list.itemClicked.connect(self._on_network_selected)
        self.network_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.network_list.customContextMenuRequested.connect(self._network_context_menu)
        layout.addWidget(self.network_list, 1)

        # Delete network button
        self._del_net_btn = QPushButton("Delete selected network")
        self._del_net_btn.setProperty("class", "danger")
        self._del_net_btn.setVisible(False)
        self._del_net_btn.clicked.connect(self._delete_selected_network)
        layout.addWidget(self._del_net_btn)

        # Separator before experiments
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {BORDER};")
        layout.addWidget(sep2)

        # Experiments section
        exp_header = QHBoxLayout()
        exp_label = QLabel("Experiments")
        exp_label.setStyleSheet("font-size: 14px; font-weight: 500;")
        exp_add_btn = QPushButton("+")
        exp_add_btn.setFixedSize(26, 26)
        exp_add_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {TEXT_MUTED};
                border: 1px solid {BORDER};
                border-radius: 6px;
                font-size: 15px;
                font-weight: 500;
                padding: 0;
            }}
            QPushButton:hover {{ color: {TEXT_PRIMARY}; border-color: {BORDER_HOVER}; background: {BG_HOVER}; }}
        """)
        exp_add_btn.clicked.connect(self._create_experiment_dialog)
        exp_header.addWidget(exp_label)
        exp_header.addStretch()
        exp_header.addWidget(exp_add_btn)
        layout.addLayout(exp_header)

        self.experiment_list = QListWidget()
        self.experiment_list.itemClicked.connect(self._on_experiment_selected)
        layout.addWidget(self.experiment_list, 1)

        self._del_exp_btn = QPushButton("Delete selected experiment")
        self._del_exp_btn.setProperty("class", "danger")
        self._del_exp_btn.setVisible(False)
        self._del_exp_btn.clicked.connect(self._delete_selected_experiment)
        layout.addWidget(self._del_exp_btn)

        return frame

    def _build_welcome_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_label = QLabel()
        icon_label.setStyleSheet(f"font-size: 48px; color: {TEXT_MUTED};")
        icon_label.setText("\u2B21")  # hexagon
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        welcome = QLabel("Welcome to EnvironNets")
        welcome.setStyleSheet("font-size: 22px; font-weight: 500; margin-top: 12px;")
        welcome.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(welcome)

        hint = QLabel("Create a bioreactor network to get started.\nClick the + button in the sidebar.")
        hint.setStyleSheet(f"font-size: 14px; color: {TEXT_SECONDARY}; margin-top: 8px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        self.content_stack.addWidget(page)  # index 0

    def _build_canvas_page(self):
        self.canvas = NetworkCanvas(api=self.api, store=self.store)
        self.content_stack.addWidget(self.canvas)  # index 1

    # -- network management ------------------------------------------------

    def _load_networks(self):
        self.network_list.clear()
        for net in self.store.list_networks():
            item = QListWidgetItem(net["name"])
            item.setData(Qt.ItemDataRole.UserRole, net["network_id"])
            self.network_list.addItem(item)

    def _on_network_selected(self, item: QListWidgetItem):
        net_id = item.data(Qt.ItemDataRole.UserRole)
        net = self.store.load_network(net_id)
        if net:
            self.current_network = net
            self.canvas.load_network(net)
            self.content_stack.setCurrentIndex(1)
            self._del_net_btn.setVisible(True)
            self.setWindowTitle(f"EnvironNets \u2014 {net.name}")
            self._load_experiments(net_id)

    def _create_network_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("New bioreactor network")
        dlg.setMinimumWidth(360)
        form = QFormLayout(dlg)

        name_input = QLineEdit()
        name_input.setPlaceholderText("e.g. Single reactor chemostat")
        desc_input = QLineEdit()
        desc_input.setPlaceholderText("Optional description")

        form.addRow("Name:", name_input)
        form.addRow("Description:", desc_input)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addWidget(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted and name_input.text().strip():
            net = Network(
                network_id=str(uuid.uuid4())[:8],
                name=name_input.text().strip(),
                description=desc_input.text().strip(),
            )
            self.store.save_network(net)
            self._load_networks()
            # Select the new network
            for i in range(self.network_list.count()):
                it = self.network_list.item(i)
                if it.data(Qt.ItemDataRole.UserRole) == net.network_id:
                    self.network_list.setCurrentItem(it)
                    self._on_network_selected(it)
                    break

    def _delete_selected_network(self):
        item = self.network_list.currentItem()
        if not item:
            return
        net_id = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "Delete network",
            f"Delete network \"{item.text()}\"? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.store.delete_network(net_id)
            self.current_network = None
            self._del_net_btn.setVisible(False)
            self._load_networks()
            self.content_stack.setCurrentIndex(0)
            self.setWindowTitle("EnvironNets")

    def _network_context_menu(self, pos):
        item = self.network_list.itemAt(pos)
        if not item:
            return
        from PyQt6.QtWidgets import QMenu
        m = QMenu(self)
        m.setStyleSheet(
            f"QMenu{{background:{BG_CARD};border:1px solid {BORDER};border-radius:6px;padding:4px}}"
            f"QMenu::item{{padding:6px 20px;border-radius:4px;color:{TEXT_SECONDARY}}}"
            f"QMenu::item:selected{{background:{BG_HOVER};color:{TEXT_PRIMARY}}}"
        )
        a_open = m.addAction("Open")
        m.addSeparator()
        a_del = m.addAction("Delete")
        choice = m.exec(self.network_list.mapToGlobal(pos))
        if choice == a_open:
            self.network_list.setCurrentItem(item)
            self._on_network_selected(item)
        elif choice == a_del:
            self.network_list.setCurrentItem(item)
            self._delete_selected_network()

    # -- experiments -------------------------------------------------------

    def _load_experiments(self, network_id: str = ""):
        self.experiment_list.clear()
        self._del_exp_btn.setVisible(False)
        nid = network_id or (self.current_network.network_id if self.current_network else "")
        if not nid:
            return
        for exp in list_experiments(self.store):
            if exp.get("network_id") == nid:
                status = exp.get("status", "draft")
                prefix = {"running": "\u25B6 ", "stopped": "\u25A0 "}.get(status, "")
                item = QListWidgetItem(f"{prefix}{exp['name']}")
                item.setData(Qt.ItemDataRole.UserRole, exp["exp_id"])
                self.experiment_list.addItem(item)

    def _on_experiment_selected(self, item: QListWidgetItem):
        exp_id = item.data(Qt.ItemDataRole.UserRole)
        exp = load_experiment(self.store, exp_id)
        if not exp or not self.current_network:
            return
        self._del_exp_btn.setVisible(True)
        panel = ExperimentPanel(self.api, self.store, exp, self.current_network)
        # Replace any previous experiment panel (index 2+)
        while self.content_stack.count() > 2:
            w = self.content_stack.widget(2)
            self.content_stack.removeWidget(w)
            w.deleteLater()
        self.content_stack.addWidget(panel)
        self.content_stack.setCurrentWidget(panel)
        self.setWindowTitle(f"EnvironNets \u2014 {self.current_network.name} \u2014 {exp.name}")

    def _create_experiment_dialog(self):
        if not self.current_network:
            QMessageBox.information(self, "No network", "Select a network first, then create an experiment.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("New experiment")
        dlg.setMinimumWidth(360)
        form = QFormLayout(dlg)

        name_input = QLineEdit()
        name_input.setPlaceholderText("e.g. Chemostat run 1")
        desc_input = QLineEdit()
        desc_input.setPlaceholderText("Optional description")

        form.addRow("Name:", name_input)
        form.addRow("Description:", desc_input)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addWidget(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted and name_input.text().strip():
            exp = Experiment(
                exp_id=str(uuid.uuid4())[:8],
                name=name_input.text().strip(),
                description=desc_input.text().strip(),
                network_id=self.current_network.network_id,
            )
            save_experiment(self.store, exp)
            self._load_experiments()
            # Auto-select the new experiment
            for i in range(self.experiment_list.count()):
                it = self.experiment_list.item(i)
                if it.data(Qt.ItemDataRole.UserRole) == exp.exp_id:
                    self.experiment_list.setCurrentItem(it)
                    self._on_experiment_selected(it)
                    break

    def _delete_selected_experiment(self):
        item = self.experiment_list.currentItem()
        if not item:
            return
        exp_id = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "Delete experiment",
            f"Delete experiment \"{item.text()}\"?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_experiment(self.store, exp_id)
            self._del_exp_btn.setVisible(False)
            self._load_experiments()
            if self.content_stack.count() > 2:
                w = self.content_stack.widget(2)
                self.content_stack.removeWidget(w)
                w.deleteLater()
            self.content_stack.setCurrentIndex(1)

    # -- connection --------------------------------------------------------

    def _open_connection_dialog(self):
        dlg = ConnectionDialog(
            current_url=self.store.get_setting("pioreactor_url", "http://localhost"),
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            url = dlg.get_url()
            self.store.set_setting("pioreactor_url", url)
            self.api = PioAPI(url)
            self.canvas.api = self.api
            current = self.content_stack.currentWidget()
            if isinstance(current, ExperimentPanel):
                current.api = self.api
                current.canvas.api = self.api
            self._check_connection()

    def _check_connection(self):
        ok = self.api.ping()
        self.connected = ok
        dot = "\u25CF"
        if ok:
            self._conn_dot.setStyleSheet(f"color: {GREEN}; font-size: 10px;")
            self._conn_dot.setText(dot)
            workers = self.api.get_workers()
            active = [w for w in workers if w.get("is_active")]
            self._conn_label.setText(f"Connected \u00b7 {len(active)} worker(s)")
            url = self.store.get_setting("pioreactor_url", "")
            short = url.replace("https://", "").replace("http://", "")[:24]
            self._conn_btn.setText(short)
        else:
            self._conn_dot.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
            self._conn_dot.setText(dot)
            self._conn_label.setText("Not connected")
            self._conn_btn.setText("Configure connection")


    def _toggle_log(self):
        vis = not self._log_panel.isVisible()
        self._log_panel.setVisible(vis)
        self._log_btn.setText("Log ▲" if vis else "Log")

    def _on_api_log(self, entry):
        ts = time.strftime("%H:%M:%S", time.localtime(entry["ts"]))
        status = entry["status"]
        color = "#4a9e6e" if isinstance(status, int) and status < 400 else "#bf5555"
        line = (f'<span style="color:#4e4e5a">{ts}</span> '
                f'<span style="color:#7c7c8a">{entry["method"]}</span> '
                f'<span style="color:#dcdce0">{entry["path"]}</span> '
                f'<span style="color:{color}">{status}</span>')
        if entry.get("detail"):
            line += f' <span style="color:#4e4e5a">{entry["detail"][:120]}</span>'
        self._log_text.append(line)
        sb = self._log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _ping_linked_units(self):
        if not self.connected or not self.current_network:
            return
        reachable = {w["pioreactor_unit"] for w in (self.api.get_workers() or []) if w.get("is_active")}
        changed = False
        for u in self.current_network.units:
            if not u.pioreactor_unit:
                if u.status != "disconnected":
                    u.status = "disconnected"; changed = True
                continue
            if u.pioreactor_unit in reachable:
                if u.status == "disconnected":
                    u.status = "idle"; changed = True
            else:
                if u.status != "disconnected":
                    u.status = "disconnected"; changed = True
        if changed:
            self.store.save_network(self.current_network)
        # Also propagate the api reference to any active ExperimentPanel
        current = self.content_stack.currentWidget()
        if isinstance(current, ExperimentPanel):
            current.api = self.api
            current.canvas.api = self.api

    def _on_source_changed(self, path: str):
        """Auto-reload when a source file is saved."""
        if not self._watcher.files() or path not in self._watcher.files():
            self._watcher.addPath(path)
        if not hasattr(self, "_reload_timer"):
            self._reload_timer = QTimer(self)
            self._reload_timer.setSingleShot(True)
            self._reload_timer.timeout.connect(self._hot_reload)
        self._reload_timer.start(300)

    def _hot_reload(self):
        """Reload UI modules and re-apply styles."""
        import environnets.ui.theme as theme_mod
        import environnets.ui.cartoons as cartoons_mod
        import environnets.ui.setup_wizard as wizard_mod
        try:
            importlib.reload(theme_mod)
            importlib.reload(cartoons_mod)
            importlib.reload(wizard_mod)
            self.setStyleSheet(theme_mod.STYLESHEET)
            self.statusBar().showMessage("Hot reload OK", 2000)
        except Exception as e:
            self.statusBar().showMessage(f"Reload error: {e}", 4000)
