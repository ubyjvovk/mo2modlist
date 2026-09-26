from pathlib import Path
import traceback

import mobase
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton, QFileDialog,
                            QInputDialog, QMessageBox, QProgressDialog)

from .mo2_modlists.core import PackError
from .mo2_modlists.manifest import (export_manifest, profile_sources, local_dependency,
                                    source_from_url)


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
        from .import_ui import ImportController
        self.importer = ImportController(self)
        return True

    def name(self):
        return "MO2 Modlists"

    def localizedName(self):
        return self.name()

    def author(self):
        return "MO2 Modlists contributors"

    def description(self):
        return "Export source manifests; resolve and install pinned modlists and review Nexus Collections."

    def version(self):
        return mobase.VersionInfo(0, 4, 0)

    def settings(self):
        return [mobase.PluginSetting("archive-directories", "Additional download directories, separated by semicolons", ""),
                mobase.PluginSetting("github-source-catalog", "Optional JSON catalog of known GitHub release URLs and archive hashes", "")]

    def archive_directories(self, root):
        extra = str(self.organizer.pluginSetting(self.name(), "archive-directories") or "")
        return [root / "downloads"] + [Path(p.strip()) for p in extra.split(";") if p.strip()]

    def displayName(self):
        return "Modlists / Export or install"

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
        dialog.setWindowTitle("MO2 Modlists — source manifests")
        dialog.resize(580, 260)
        layout = QVBoxLayout(dialog)
        label = QLabel(f"Current profile: {profile}\n\nExport one modlist.json containing Nexus, GitHub or local archive references.\n"
                       "Unknown sources: choose a local archive, provide a URL, or explicitly skip.\n"
                       "Import resolves sources and creates a separate profile. Unknown dependencies require a recipe.\n"
                       "Local edits and unrecorded installer choices are not exported.")
        label.setWordWrap(True)
        layout.addWidget(label)
        export = QPushButton("Export modlist.json…")
        layout.addWidget(export)
        export.clicked.connect(lambda: self.export_clicked(dialog, root, game, profile))
        install = QPushButton("Install modlist.json or lock…")
        collection = QPushButton("Import Nexus Collection…")
        layout.addWidget(install)
        layout.addWidget(collection)
        install.clicked.connect(lambda: self.importer.open_manifest(dialog, root, game))
        collection.clicked.connect(lambda: self.importer.open_collection(dialog, root, game))
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
        destination, _ = QFileDialog.getSaveFileName(parent, "Export source manifest", "modlist.json", "Modlist (*.json)")
        if not destination:
            return
        manifest = Path(destination)
        if manifest.exists():
            QMessageBox.warning(parent, self.name(), "Choose a new filename; existing manifests are preserved.")
            return
        self.organizer.refresh(True)
        archives = self.archive_directories(root)
        catalog = str(self.organizer.pluginSetting(self.name(), "github-source-catalog") or "")
        def choose_sources(candidates):
            selections = {}
            for item in candidates:
                name, dependency = item["name"], item["dependency"]
                while dependency is None:
                    choice = QMessageBox(parent)
                    choice.setWindowTitle("Choose source — " + name)
                    choice.setText(f"No source is recorded for '{name}'.\nChoose an existing local ZIP/7z for testing, provide a source URL, or skip this mod.")
                    local = choice.addButton("Local archive…", QMessageBox.ButtonRole.ActionRole)
                    remote = choice.addButton("Source URL…", QMessageBox.ButtonRole.ActionRole)
                    skip = choice.addButton("Skip mod", QMessageBox.ButtonRole.DestructiveRole)
                    choice.addButton(QMessageBox.StandardButton.Cancel)
                    choice.exec()
                    clicked = choice.clickedButton()
                    try:
                        if clicked == local:
                            filename, _ = QFileDialog.getOpenFileName(parent, "Source archive for " + name, "", "Archives (*.zip *.7z)")
                            if filename:
                                # Hashing runs in the worker below, keeping the dialog responsive.
                                dependency = {"localSelection": filename}
                        elif clicked == remote:
                            url, ok = QInputDialog.getText(parent, "Source URL for " + name,
                                "Nexus mod/file page or exact GitHub release asset URL:")
                            if ok and url:
                                dependency = {"source": source_from_url(url)}
                        elif clicked == skip:
                            break
                        else:
                            return  # Cancel the entire export; no output was written.
                    except PackError as exc:
                        QMessageBox.warning(parent, "Invalid source", str(exc))
                selections[name] = dependency
            def write(report):
                resolved = {}
                for name, dependency in selections.items():
                    report("Recording " + name)
                    resolved[name] = local_dependency(Path(dependency["localSelection"]), manifest) if dependency and "localSelection" in dependency else dependency
                return export_manifest(root, game, profile, manifest, resolved, report)
            def finished(result):
                skipped = "\nSkipped: " + ", ".join(result["skipped"]) if result["skipped"] else ""
                QMessageBox.information(parent, "Manifest exported",
                    f"{result['dependencies']} dependencies written to:\n{manifest}\n{skipped}\n\n{result['notice']}")
            self.run_job(parent, write, finished)
        self.run_job(parent, lambda report: profile_sources(root, profile, archives,
                      Path(catalog) if catalog else None), choose_sources)
