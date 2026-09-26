"""MO2-owned UI and download bridge for the source-manifest importer."""
import json
from pathlib import Path
import threading

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from .mo2_modlists.acquisition import ArtifactStore, InputRequired
from .mo2_modlists.core import PackError, json_digest, write_json
from .mo2_modlists.install import import_lock, validate_lock
from .mo2_modlists.manifest import validate_manifest
from .mo2_modlists.planning import resolve_manifest


class ImportController(QObject):
    request = pyqtSignal(object)

    def __init__(self, tool):
        super().__init__()
        self.tool = tool
        self.pending = {}
        self.request.connect(self.handle_request)
        manager = tool.organizer.downloadManager()
        manager.onDownloadComplete(self.download_complete)
        manager.onDownloadFailed(self.download_failed)

    def ask(self, request):
        pending = {"request": request, "event": threading.Event()}
        self.request.emit(pending)
        while not pending["event"].wait(0.1):
            if QThread.currentThread().isInterruptionRequested():
                pending["cancelled"] = True
                raise PackError("Cancelled; verified downloads and installation staging are retained")
        if "error" in pending:
            raise PackError(pending["error"])
        return pending.get("answer")

    def handle_request(self, pending):
        if pending.get("cancelled"):
            return
        request = pending["request"]
        parent = self.tool.parent
        try:
            kind = request["kind"]
            if kind == "nexus-download":
                source = request["source"]
                manager = self.tool.organizer.downloadManager()
                download_id = manager.startDownloadNexusFileForGame(source["game"], source["modId"], source["fileId"])
                if download_id < 0:
                    raise PackError("MO2 could not start this Nexus download. Connect Nexus in MO2 or supply the exact archive in Downloads.")
                self.pending[download_id] = pending
                return
            if kind == "local-archive":
                filename, _ = QFileDialog.getOpenFileName(parent, request["message"], "", "Archives (*.zip *.7z)")
                if not filename:
                    raise PackError("Archive selection cancelled")
                answer = filename
            elif kind == "dependency-metadata":
                filename, _ = QFileDialog.getOpenFileName(parent,
                    "Dependency recipe: " + " → ".join(request.get("chain", [])), "", "Recipe (*.json)")
                if not filename:
                    raise PackError("Recipe selection cancelled; the plan remains incomplete")
                answer = Path(filename).resolve().as_posix()
            elif kind in ("recipe-option", "file-conflict", "registry-recipe"):
                values = request.get("choices", request.get("owners"))
                labels = [str(v) for v in request.get("labels", values)]
                # Include index so equal display names remain distinguishable.
                labels = [f"{i + 1}. {label}" for i, label in enumerate(labels)]
                choice, accepted = QInputDialog.getItem(parent, "Resolve installation choice", request["message"], labels, 0, False)
                if not accepted:
                    raise PackError("Installation choice cancelled; the plan remains incomplete")
                answer = values[labels.index(choice)]
            else:
                raise InputRequired(**request)
            pending["answer"] = answer
        except Exception as exc:
            pending["error"] = str(exc)
        pending["event"].set()

    def download_complete(self, download_id):
        pending = self.pending.pop(download_id, None)
        if pending is not None:
            try:
                pending["answer"] = self.tool.organizer.downloadManager().downloadPath(download_id)
            except Exception as exc:
                pending["error"] = str(exc)
            pending["event"].set()

    def download_failed(self, download_id):
        pending = self.pending.pop(download_id, None)
        if pending is not None:
            pending["error"] = "Nexus download failed. Check MO2 Downloads and retry; no profile was activated."
            pending["event"].set()

    def store(self, root, archives, report):
        return ArtifactStore(root / ".modlists/source-cache", archives, progress=report,
            nexus_fetch=lambda source: self.ask({"kind": "nexus-download", "source": source}), manual_fetch=self.ask)

    def open_manifest(self, parent, root, game, filename=None):
        if filename is None:
            filename, _ = QFileDialog.getOpenFileName(parent, "Install source modlist", "", "Manifest or lock (*.json)")
        if not filename:
            return
        path = Path(filename).resolve()
        try:
            selected = json.loads(path.read_text(encoding="utf-8-sig"))
            if selected.get("kind") == "source-installation":
                lock_path = path
                candidate = path.with_name(path.name.replace(".lock.json", ".json"))
                if candidate == path or not candidate.is_file():
                    filename, _ = QFileDialog.getOpenFileName(parent, "Select matching source manifest", str(path.parent), "Manifest (*.json)")
                    if not filename:
                        return
                    candidate = Path(filename)
                path = candidate
                document = validate_manifest(json.loads(path.read_text(encoding="utf-8-sig")))
                validate_lock(selected, document)
            else:
                document = validate_manifest(selected)
                lock_path = path.with_name(path.stem + ".lock.json")
            name, accepted = QInputDialog.getText(parent, "New MO2 profile", "Create profile:", text=document["name"] + " - Imported")
            if not accepted or not name:
                return
            if (root / "profiles" / name).exists():
                raise PackError("Choose a new profile name; existing profiles are preserved")
        except Exception as exc:
            QMessageBox.critical(parent, "Invalid modlist", str(exc))
            return
        archives = self.tool.archive_directories(root)
        choices_path = lock_path.with_name(lock_path.name + ".choices.json")

        def plan(report):
            if lock_path.exists():
                lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
                validate_lock(lock, document)
                return lock
            choices = {"manifestSha256": json_digest(document), "answers": {}}
            if choices_path.exists():
                choices = json.loads(choices_path.read_text(encoding="utf-8-sig"))
                if choices["manifestSha256"] != json_digest(document):
                    raise PackError("Saved resolution choices belong to a changed manifest; choose a new lock destination")
            def ask(request):
                key = json_digest(request)
                if key not in choices["answers"]:
                    choices["answers"][key] = self.ask(request)
                    write_json(choices_path, choices)
                return choices["answers"][key]
            return resolve_manifest(path, self.store(root, archives, report), game, lock_path, progress=report, ask=ask)

        def review(lock):
            root_entries = {e["path"] for p in lock["packages"].values() for e in p["outputs"] if e["class"] == "game-root"}
            text = f"Create '{name}' with {len(lock['packages'])} components from the pinned source lock.\n\n"
            if root_entries:
                text += f"Deploy {len(root_entries)} physical game-folder files. This affects every profile using this game. Changed originals are backed up.\n\n"
            text += "File contents and overwrite winners have been inspected. Runtime conflicts inside different .archive files cannot be detected by this check."
            message = QMessageBox(QMessageBox.Icon.Question, "Review source installation", text,
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel, parent)
            message.setDetailedText(json.dumps({"components": [{"component": p["component"], "version": p["version"],
                "source": p["artifact"]["source"], "sha256": p["artifact"]["sha256"], "reason": p["reason"], "options": p["options"]}
                for p in lock["packages"].values()], "physicalGameFiles": sorted(root_entries),
                "externalPrerequisites": lock["externalPrerequisites"], "lock": str(lock_path)}, indent=2))
            if message.exec() != QMessageBox.StandardButton.Ok:
                return
            def install(report):
                return import_lock(path, lock_path, self.store(root, archives, report), root, game, name,
                    allow_root=bool(root_entries), progress=report)
            def completed(result):
                self.tool.organizer.refresh(False)
                QMessageBox.information(parent, "Source installation complete",
                    f"Created '{name}' with {len(result['mods'])} components.\nRestart MO2 to refresh its profile selector, then select the new profile.\n\nLock: {lock_path}")
            self.tool.run_job(parent, install, completed)
        self.tool.run_job(parent, plan, review)

    def open_collection(self, parent, root, game):
        from .mo2_modlists.collections import read_collection, fetch_collection, convert_collection, write_collection_manifest
        choice, accepted = QInputDialog.getItem(parent, "Import Nexus Collection", "Collection source:",
            ["Downloaded collection package", "Nexus Collection URL"], 0, False)
        if not accepted:
            return
        if choice == "Nexus Collection URL":
            source, accepted = QInputDialog.getText(parent, "Nexus Collection", "Collection URL or NXM revision link:")
            if not accepted or not source:
                return
        else:
            source, _ = QFileDialog.getOpenFileName(parent, "Full collection package", "", "Collection (*.7z *.zip *.json)")
            if not source:
                return
        output, _ = QFileDialog.getSaveFileName(parent, "Save converted source manifest", "modlist.json", "Manifest (*.json)")
        if not output:
            return
        destination = Path(output)
        def load(report):
            if choice == "Nexus Collection URL":
                path, identity = fetch_collection(source, root / ".modlists/source-cache", progress=report)
            else:
                path, identity = Path(source), None
            return read_collection(path), identity
        def review(loaded):
            document, identity = loaded
            decisions = {}
            for index, mod in enumerate(document["mods"], 1):
                if mod.get("optional"):
                    answer = QMessageBox.question(parent, "Optional collection mod", "Include " + mod.get("name", str(index)) + "?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
                    if answer == QMessageBox.StandardButton.Cancel:
                        return
                    decisions[f"mod-{index:04d}"] = {"include": answer == QMessageBox.StandardButton.Yes}
            draft = convert_collection(document, identity=identity, decisions=decisions)
            if draft["pending"]:
                review_path = destination.with_name(destination.stem + ".collection-review.json")
                if review_path.exists():
                    QMessageBox.warning(parent, "Review exists", "Choose a new destination to preserve the existing review")
                    return
                write_json(review_path, draft)
                message = QMessageBox(QMessageBox.Icon.Information, "Collection needs review",
                    f"{len(draft['pending'])} required choices or unsupported instructions remain. The full collection and draft are saved at:\n{review_path}\n\nNo installable manifest or profile was created.", parent=parent)
                message.setDetailedText(json.dumps(draft["pending"], indent=2))
                message.exec()
                return
            try:
                write_collection_manifest(draft, destination)
            except PackError as exc:
                QMessageBox.warning(parent, "Collection conversion", str(exc))
                return
            self.open_manifest(parent, root, game, str(destination))
        self.tool.run_job(parent, load, review)
