from pathlib import Path
import json
import traceback
import threading

import mobase
from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton, QFileDialog,
                            QInputDialog, QMessageBox, QProgressDialog, QPlainTextEdit)

from .mo2_modlists.core import PackError, export_profile, import_profile, load_bundle
from .mo2_modlists.sources import hydrate_bundle, export_source_profile


class NexusBridge(QObject):
    request = pyqtSignal(object)


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
        self.pending_downloads = {}
        self.bridge = NexusBridge()
        self.bridge.request.connect(self.start_nexus_download)
        manager = organizer.downloadManager()
        manager.onDownloadComplete(self.nexus_complete)
        manager.onDownloadFailed(self.nexus_failed)
        return True

    def start_nexus_download(self, pending):
        try:
            source = pending["source"]
            download_id = self.organizer.downloadManager().startDownloadNexusFileForGame(
                source["game"], source["modId"], source["fileId"])
            if download_id < 0:
                raise PackError("MO2 could not start this Nexus download. Check its Nexus connection or supply the archive in Downloads.")
            self.pending_downloads[download_id] = pending
        except Exception as exc:
            pending["error"] = str(exc)
            pending["event"].set()

    def nexus_complete(self, download_id):
        pending = self.pending_downloads.pop(download_id, None)
        if pending is not None:
            try:
                pending["path"] = self.organizer.downloadManager().downloadPath(download_id)
            except Exception as exc:
                pending["error"] = str(exc)
            finally:
                pending["event"].set()

    def nexus_failed(self, download_id):
        pending = self.pending_downloads.pop(download_id, None)
        if pending is not None:
            pending["error"] = "Nexus download failed. Check MO2 Downloads or supply the exact archive manually."
            pending["event"].set()

    def fetch_nexus(self, source):
        pending = {"source": source, "event": threading.Event()}
        self.bridge.request.emit(pending)
        while not pending["event"].wait(0.25):
            if QThread.currentThread().isInterruptionRequested():
                raise PackError("Import cancelled; any in-progress Nexus download remains in MO2 Downloads")
        if "error" in pending:
            raise PackError(pending["error"])
        return pending["path"]

    def name(self):
        return "MO2 Modlists"

    def localizedName(self):
        return self.name()

    def author(self):
        return "MO2 Modlists contributors"

    def description(self):
        return "Export and import verified, private profile bundles."

    def version(self):
        return mobase.VersionInfo(0, 2, 0)

    def settings(self):
        return [mobase.PluginSetting("archive-directories", "Additional download directories, separated by semicolons", ""),
                mobase.PluginSetting("github-source-catalog", "Optional JSON catalog of known GitHub release URLs and archive hashes", "")]

    def archive_directories(self, root):
        extra = str(self.organizer.pluginSetting(self.name(), "archive-directories") or "")
        return [root / "downloads"] + [Path(p.strip()) for p in extra.split(";") if p.strip()]

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
                       "Pinned source archives can be reconstructed; new dependency resolution is pending.")
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
        archives = self.archive_directories(root)
        catalog = str(self.organizer.pluginSetting(self.name(), "github-source-catalog") or "")
        self.run_job(parent, lambda report: export_source_profile(root, game, profile, bundle, archives,
                                                                 Path(catalog) if catalog else None, progress=report),
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
                            f"Use {len(lock.get('sourceArtifacts', {}))} pinned source archives where needed.\n"
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

        def restore(report):
            hydrate_bundle(bundle, root / ".modlists/source-cache", archive_dirs,
                           download=True, progress=report, nexus_fetcher=self.fetch_nexus)
            return import_profile(bundle, root, game, name, allow_root=True, progress=report, manage_ini=False)
        archive_dirs = self.archive_directories(root)
        self.run_job(parent, restore, completed)
