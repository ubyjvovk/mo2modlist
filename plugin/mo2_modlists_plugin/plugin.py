from pathlib import Path
import json
import time
import traceback

import mobase
from PyQt6.QtCore import QThread, QTimer, QCoreApplication, pyqtSignal, Qt, qWarning
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton, QFileDialog,
                            QInputDialog, QMessageBox, QProgressDialog)

from .mo2_modlists.core import PackError
from .mo2_modlists.games import detect_game
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


class ModlistsTool(mobase.IPluginTool, mobase.IPluginFileMapper):
    def __init__(self):
        mobase.IPluginTool.__init__(self)
        mobase.IPluginFileMapper.__init__(self)
        self.organizer = None
        self.parent = None
        self.update_worker = None

    def init(self, organizer):
        self.organizer = organizer
        from .import_ui import ImportController
        self.importer = ImportController(self)
        organizer.onUserInterfaceInitialized(self.start_update_checks)
        return True

    def start_update_checks(self, window):
        self.update_window = window
        self.update_timer = QTimer(window)
        self.update_timer.setInterval(60 * 60 * 1000)
        self.update_timer.timeout.connect(self.background_update_check)
        self.update_timer.start()
        QTimer.singleShot(5000, self.background_update_check)
        QCoreApplication.instance().aboutToQuit.connect(self.stop_update_check)

    def stop_update_check(self):
        if self.update_worker is not None and self.update_worker.isRunning():
            self.update_worker.requestInterruption()
            self.update_worker.wait()

    def background_update_check(self):
        if self.update_worker is not None:
            return
        if not self.organizer.pluginSetting(self.name(), "check-manifest-updates"):
            return
        from .mo2_modlists.remote_manifests import check_manifest_updates
        from .mo2_modlists.core import json_digest, write_json
        try:
            root, _, profile = self.paths()
            manifest = root / "profiles" / profile / "modlist.json"
            if not manifest.is_file() or not json.loads(manifest.read_text(encoding="utf-8-sig")).get("extensions", {}).get("remoteManifests"):
                return
            state_path = root / ".modlists/update-checks" / (json_digest(profile) + ".json")
            previous = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
            if 0 <= time.time() - previous.get("checkedAt", 0) < 24 * 60 * 60:
                return
        except (OSError, ValueError, TypeError, AttributeError, PackError) as exc:
            qWarning("MO2 Modlists update check: " + str(exc))
            return
        worker = Worker(lambda report: check_manifest_updates(root / "profiles" / profile, progress=report), self.update_window)
        self.update_worker = worker
        def completed(results):
            changed = [r for r in results if r["status"] == "available"]
            notice = json_digest(changed) if changed else None
            try:
                write_json(state_path, {"checkedAt": time.time(), "results": results, "notice": notice})
            except OSError as exc:
                qWarning("MO2 Modlists: cannot save update-check status: " + str(exc))
            if changed and notice != previous.get("notice"):
                self.update_window.statusBar().showMessage(
                    f"MO2 Modlists: {len(changed)} manifest update(s) for '{profile}'. Open Tools → Modlists → Check manifest updates to review.", 30000)
            for result in results:
                if result["status"] == "error":
                    qWarning("MO2 Modlists update check: " + result["error"])
        worker.result.connect(completed)
        worker.error.connect(lambda error: qWarning("MO2 Modlists update check: " + error))
        def finished():
            self.update_worker = None
            worker.deleteLater()
        worker.finished.connect(finished)
        worker.start()

    def name(self):
        return "MO2 Modlists"

    def mappings(self):
        import json
        from PyQt6.QtCore import qWarning
        from .mo2_modlists.runtime_mapping import cet_root_files
        profile = Path(self.organizer.profilePath())
        lock_path = profile / "modlist.lock.json"
        if not lock_path.is_file():
            return []
        try:
            game = Path(self.organizer.managedGame().gameDirectory().absolutePath())
            lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
            result = []
            for rel, target in cet_root_files(lock, game):
                # Existing enabled mod/Overwrite mappings retain their priority.
                origins = self.organizer.findFiles(str(Path(rel).parent), target.name)
                if origins and Path(origins[0]).resolve() != target.resolve():
                    continue
                result.append(mobase.Mapping(str(target), str(target), False, False))
            return result
        except (OSError, ValueError, KeyError, TypeError, PackError) as exc:
            qWarning("MO2 Modlists: cannot map CET runtime files: " + str(exc))
            return []

    def localizedName(self):
        return self.name()

    def author(self):
        return "MO2 Modlists contributors"

    def description(self):
        return "Export source manifests; resolve and install pinned modlists and review Nexus Collections."

    def version(self):
        return mobase.VersionInfo(0, 10, 0)

    def settings(self):
        return [mobase.PluginSetting("archive-directories", "Additional download directories, separated by semicolons", ""),
                mobase.PluginSetting("github-source-catalog", "Optional JSON catalog of known GitHub release URLs and archive hashes", ""),
                mobase.PluginSetting("check-manifest-updates", "Check tracked manifest URLs daily while MO2 is open (never installs automatically)", True)]

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
        label = QLabel(f"Current profile: {profile}\n\nUse one package.json for a mod or collection, with named dependencies and install instructions.\n"
                       "Unknown sources: choose a local archive, provide a URL, or explicitly skip.\n"
                       "Install into a new profile or add to the current profile with dependency re-resolution.\n"
                       "Local edits and unrecorded installer choices are not exported.")
        label.setWordWrap(True)
        layout.addWidget(label)
        export = QPushButton("Export package.json…")
        layout.addWidget(export)
        export.clicked.connect(lambda: self.export_clicked(dialog, root, game, profile))
        from_url = QPushButton("Create manifest from Nexus URL…")
        layout.addWidget(from_url)
        from_url.clicked.connect(lambda: self.importer.open_url(dialog, root, game))
        install = QPushButton("Install package.json or lock…")
        collection = QPushButton("Import Nexus Collection…")
        layout.addWidget(install)
        layout.addWidget(collection)
        install.clicked.connect(lambda: self.importer.open_manifest(dialog, root, game))
        add = QPushButton("Add mod/modlist to current profile…")
        layout.addWidget(add)
        add.clicked.connect(lambda: self.importer.add_to_profile(dialog, root, game, profile))
        remote = QPushButton("Install manifest from URL…")
        layout.addWidget(remote)
        remote.clicked.connect(lambda: self.importer.open_manifest_url(dialog, root, game, profile))
        updates = QPushButton("Check manifest updates…")
        layout.addWidget(updates)
        updates.clicked.connect(lambda: self.importer.check_updates(dialog, root, game, profile))
        collection.clicked.connect(lambda: self.importer.open_collection(dialog, root, game))
        restore = QPushButton("Restore imported game-root files…")
        layout.addWidget(restore)
        restore.clicked.connect(lambda: self.importer.open_restoration(dialog, root, game))
        providers = QPushButton("Optional provider credentials…")
        layout.addWidget(providers)
        providers.clicked.connect(lambda: self.importer.configure_provider(dialog))
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
        destination, _ = QFileDialog.getSaveFileName(parent, "Export package definition", "package.json", "Package (*.json)")
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
                return export_manifest(root, game, profile, manifest, resolved, report,
                    store=self.importer.store(root, archives, report), ask=self.importer.ask)
            def finished(result):
                skipped = "\nSkipped: " + ", ".join(result["skipped"]) if result["skipped"] else ""
                QMessageBox.information(parent, "Manifest exported",
                    f"{result['dependencies']} dependencies written to:\n{manifest}\n{skipped}\n\n{result['notice']}")
            self.run_job(parent, write, finished)
        self.run_job(parent, lambda report: profile_sources(root, profile, archives,
                      Path(catalog) if catalog else None, game_id=detect_game(game)), choose_sources)
