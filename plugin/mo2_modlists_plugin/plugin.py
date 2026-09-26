from pathlib import Path
import json
import traceback

import mobase
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton, QFileDialog,
                            QInputDialog, QMessageBox, QProgressDialog, QPlainTextEdit)

from .mo2_modlists.core import PackError, export_profile, import_profile, load_bundle


class Worker(QThread):
    progress = pyqtSignal(str)
    result = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, function, parent):
        super().__init__(parent)
        self.function = function

    def report(self, text):
        if self.isInterruptionRequested():
            raise PackError("Operation cancelled")
        self.progress.emit(text)

    def run(self):
        try:
            self.result.emit(self.function(self.report))
        except Exception:
            self.error.emit(traceback.format_exc())


class ModlistsTool(mobase.IPluginTool):
    def __init__(self):
        super().__init__()
        self.organizer = None
        self.parent = None

    def init(self, organizer):
        self.organizer = organizer
        return True

    def name(self):
        return "MO2 Modlists"

    def localizedName(self):
        return self.name()

    def author(self):
        return "MO2 Modlists contributors"

    def description(self):
        return "Export and import verified, private profile bundles."

    def version(self):
        return mobase.VersionInfo(0, 1, 0)

    def settings(self):
        return []

    def displayName(self):
        return "Modlists / Export or import profile"

    def tooltip(self):
        return self.description()

    def icon(self):
        return QIcon()

    def setParentWidget(self, widget):
        self.parent = widget

    def paths(self):
        profile = Path(self.organizer.profilePath()).resolve()
        root = profile.parent.parent
        if Path(self.organizer.modsPath()).resolve() != root / "mods":
            raise PackError("This preview requires mods and profiles inside the same instance directory.")
        if Path(self.organizer.overwritePath()).resolve() != root / "overwrite":
            raise PackError("This preview requires the default overwrite directory.")
        game = Path(self.organizer.managedGame().gameDirectory().absolutePath())
        return root, game, profile.name

    def display(self):
        try:
            root, game, profile = self.paths()
        except Exception as exc:
            QMessageBox.critical(self.parent, self.name(), str(exc))
            return
        dialog = QDialog(self.parent)
        dialog.setWindowTitle("MO2 Modlists — profile round trip")
        dialog.resize(580, 260)
        layout = QVBoxLayout(dialog)
        label = QLabel(f"Current profile: {profile}\n\nExport installed mod choices and ordering, then import into a new profile.\n"
                       "Bundles contain local mod files and are for personal backup/transfer.\n"
                       "This preview reads locked bundles; remote dependency resolution is pending.")
        label.setWordWrap(True)
        layout.addWidget(label)
        export = QPushButton("Export current profile…")
        restore = QPushButton("Import modlist.json…")
        layout.addWidget(export)
        layout.addWidget(restore)
        export.clicked.connect(lambda: self.export_clicked(dialog, root, game, profile))
        restore.clicked.connect(lambda: self.import_clicked(dialog, root, game))
        dialog.exec()

    def run_job(self, parent, function, done):
        progress = QProgressDialog("Preparing…", "Cancel", 0, 0, parent)
        progress.setWindowTitle(self.name())
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        worker = Worker(function, progress)
        outcome = {}
        worker.progress.connect(progress.setLabelText)
        worker.result.connect(lambda value: outcome.update(result=value))
        worker.error.connect(lambda value: outcome.update(error=value))
        progress.canceled.connect(worker.requestInterruption)
        worker.finished.connect(progress.accept)
        worker.start()
        progress.exec()
        # Cancellation requests cooperative rollback. Do not destroy a running worker.
        if worker.isRunning():
            progress.setCancelButton(None)
            progress.setLabelText("Finishing current file and cancelling safely…")
            progress.exec()
        worker.wait()
        if "error" in outcome:
            message = QMessageBox(QMessageBox.Icon.Critical, self.name(),
                                  outcome["error"].splitlines()[-1], parent=parent)
            message.setDetailedText(outcome["error"])
            message.exec()
        elif "result" in outcome:
            done(outcome["result"])

    def export_clicked(self, parent, root, game, profile):
        destination = QFileDialog.getExistingDirectory(parent, "Choose parent folder for export")
        if not destination:
            return
        name, accepted = QInputDialog.getText(parent, "Export bundle", "New folder name:", text=profile + "-export")
        if not accepted or not name:
            return
        from .mo2_modlists.core import safe_relative
        try:
            if "/" in safe_relative(name):
                raise PackError("Choose one folder name")
        except PackError as exc:
            QMessageBox.warning(parent, self.name(), str(exc))
            return
        self.organizer.refresh(True)
        bundle = Path(destination) / name
        self.run_job(parent, lambda report: export_profile(root, game, profile, bundle, progress=report),
                     lambda result: QMessageBox.information(parent, "Export complete",
                         f"{result['mods']} mods exported.\n\n{bundle / 'modlist.json'}"))

    def import_clicked(self, parent, root, game):
        filename, _ = QFileDialog.getOpenFileName(parent, "Open exported modlist", "", "Modlist (*.json)")
        if not filename:
            return
        bundle = Path(filename).parent
        try:
            lock = load_bundle(bundle)
        except Exception as exc:
            QMessageBox.critical(parent, self.name(), str(exc))
            return
        name, accepted = QInputDialog.getText(parent, "New profile", "Profile name:", text=lock["profile"] + " - Imported")
        if not accepted or not name:
            return
        review = QMessageBox(QMessageBox.Icon.Question, "Review import",
                            f"Create profile '{name}' with {len(lock['layers'])} mods.\n"
                            f"Restore {len(lock['overwrite'])} generated/settings files as the highest-priority mod.\n"
                            f"Deploy {len(lock['root'])} physical game-root files if their contents differ.\n\n"
                            "Root files and CP77 support-plugin settings affect all profiles using this game. "
                            "Changed root files are backed up. Existing mod directories are preserved.",
                            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel, parent)
        review.setDetailedText("\n".join(e["path"] for e in lock["root"]) +
                               "\n\nCP77 plugin settings:\n" + json.dumps(lock.get("mo2GameSettings", {}), indent=2))
        if review.exec() != QMessageBox.StandardButton.Ok:
            return

        def completed(result):
            for key, value in result["mo2GameSettings"].items():
                converted = value.lower() == "true" if value.lower() in ("true", "false") else value
                self.organizer.setPluginSetting("Cyberpunk 2077 Support Plugin", key, converted)
            self.organizer.refresh(False)
            QMessageBox.information(parent, "Import complete",
                                    f"Profile '{name}' is ready.\nRestart MO2 to refresh the profile selector, then select it and launch the game.")

        self.run_job(parent, lambda report: import_profile(bundle, root, game, name, allow_root=True, progress=report, manage_ini=False), completed)
