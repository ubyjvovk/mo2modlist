"""MO2-owned UI and download bridge for the source-manifest importer."""
import json
from pathlib import Path
import threading

from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QLineEdit

from .mo2_modlists.acquisition import ArtifactStore, InputRequired, json_request
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
                if hasattr(manager, "startDownloadNexusFileForGame"):
                    download_id = manager.startDownloadNexusFileForGame(source["game"], source["modId"], source["fileId"])
                else:
                    current_game = self.tool.organizer.managedGame().gameNexusName()
                    if current_game.casefold() != source["game"].casefold():
                        raise PackError("This MO2 download API only supports its currently managed game")
                    download_id = manager.startDownloadNexusFile(source["modId"], source["fileId"])
                if download_id < 0:
                    pending["answer"] = self.choose_nexus_archive(parent, source,
                        "MO2 could not start this download. You can supply the exact archive downloaded through Nexus's supported website flow.")
                    pending["event"].set()
                    return
                self.pending[download_id] = pending
                return
            if kind == "nexus-archive":
                answer = self.choose_nexus_archive(parent, request["source"], request["message"])
            elif kind == "local-archive":
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
            elif kind in ("recipe-option", "file-conflict", "registry-recipe", "nexus-file", "nexus-dependency"):
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
            if pending.get("cancelled"):
                pending["event"].set()
                return
            try:
                pending["answer"] = self.choose_nexus_archive(self.tool.parent, pending["request"]["source"],
                    "The MO2 download failed. Supply the exact archive if you downloaded it manually, or cancel to retry later.")
            except Exception as exc:
                pending["error"] = str(exc)
            pending["event"].set()

    def choose_nexus_archive(self, parent, source, message):
        url = f"https://www.nexusmods.com/{source['game']}/mods/{source['modId']}?tab=files&file_id={source['fileId']}"
        question = QMessageBox(QMessageBox.Icon.Question, "Nexus manual download",
            message + "\n\nExact source:\n" + url + "\n\nSelect its downloaded archive? Any pinned hash will be verified.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel, parent)
        question.setTextFormat(Qt.TextFormat.PlainText)
        if question.exec() != QMessageBox.StandardButton.Ok:
            raise PackError("Nexus manual download cancelled; the plan remains incomplete")
        filename, _ = QFileDialog.getOpenFileName(parent, "Exact downloaded Nexus archive", "", "Archives (*.zip *.7z)")
        if not filename:
            raise PackError("Nexus archive selection cancelled; the plan remains incomplete")
        return filename

    def store(self, root, archives, report):
        from .mo2_modlists.credentials import headers
        from .mo2_modlists.nexus import NexusProvider
        github_headers = headers("github")
        nexus_headers = headers("nexus")
        def nexus_fetch(source):
            if nexus_headers:
                if not hasattr(self, "nexus_premium"):
                    account = json_request("https://api.nexusmods.com/v1/users/validate.json", headers=nexus_headers)
                    self.nexus_premium = bool(account.get("is_premium"))
                if not self.nexus_premium:
                    return self.ask({"kind": "nexus-archive", "source": source,
                        "message": "This Nexus account requires the website download flow. Download this exact file, then select its ZIP/7z. Existing cached bytes are reused automatically."})
            return self.ask({"kind": "nexus-download", "source": source})
        return ArtifactStore(root / ".modlists/source-cache", archives, progress=report,
            nexus_fetch=nexus_fetch, manual_fetch=self.ask,
            nexus_metadata=NexusProvider(nexus_headers) if nexus_headers else None,
            request=lambda url: json_request(url, headers=github_headers))

    def configure_provider(self, parent):
        from .mo2_modlists.credentials import save, remove
        label, accepted = QInputDialog.getItem(parent, "Optional provider sign-in", "Credential to configure:",
            ["Nexus API key", "GitHub token"], 0, False)
        if not accepted:
            return
        provider = "nexus" if label == "Nexus API key" else "github"
        action, accepted = QInputDialog.getItem(parent, label, "Store or remove this extension's credential:",
            ["Store credential", "Remove stored credential"], 0, False)
        if not accepted:
            return
        try:
            if action == "Remove stored credential":
                remove(provider)
            else:
                location = "https://www.nexusmods.com/settings/api-keys" if provider == "nexus" else "https://github.com/settings/tokens"
                secret, accepted = QInputDialog.getText(parent, label,
                    f"Create your own credential using the provider's supported flow:\n{location}\n\n"
                    "It is stored only in Windows Credential Manager. MO2's existing Nexus sign-in still handles individual mod downloads.\n"
                    "This optional key enables Collection/API metadata requests.\n\nCredential:", QLineEdit.EchoMode.Password)
                if not accepted:
                    return
                save(provider, secret)
            if provider == "nexus" and hasattr(self, "nexus_premium"):
                del self.nexus_premium
            QMessageBox.information(parent, "Provider credential", "Credential updated in Windows Credential Manager. It is never exported into manifests or locks.")
        except PackError as exc:
            QMessageBox.warning(parent, "Provider credential", str(exc))

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
            acknowledged = []
            for requirement in lock.get("externalPrerequisites", []):
                question = QMessageBox(QMessageBox.Icon.Question, "Required Collection instructions",
                    requirement["notice"] + "\n\n" + requirement["text"] + "\n\nHave these steps been completed for this target?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, parent)
                question.setTextFormat(Qt.TextFormat.PlainText)
                if question.exec() != QMessageBox.StandardButton.Yes:
                    return
                acknowledged.append(requirement["id"])
            root_entries = {e["path"] for p in lock["packages"].values() for e in p["outputs"] if e["class"] == "game-root"}
            text = f"Create '{name}' with {len(lock['packages'])} components from the pinned source lock.\n\n"
            if root_entries:
                text += f"Deploy {len(root_entries)} physical game-folder files. This affects every profile using this game. Changed originals are backed up.\n\n"
            text += "File contents and overwrite winners have been inspected. Runtime conflicts inside different .archive files cannot be detected by this check."
            message = QMessageBox(QMessageBox.Icon.Question, "Review source installation", text,
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel, parent)
            message.setDetailedText(json.dumps({"components": [{"component": p["component"], "version": p["version"],
                "source": p["artifact"]["source"], "sha256": p["artifact"]["sha256"], "reason": p["reason"], "options": p["options"],
                "metadata": p.get("metadataProvenance"), "recipeSha256": p["recipe"]["sha256"]}
                for p in lock["packages"].values()], "physicalGameFiles": sorted(root_entries),
                "externalPrerequisites": lock["externalPrerequisites"], "collectionHandoffs": lock.get("collection", {}).get("manualHandoffs", {}),
                "lock": str(lock_path)}, indent=2))
            if message.exec() != QMessageBox.StandardButton.Ok:
                return
            def install(report):
                return import_lock(path, lock_path, self.store(root, archives, report), root, game, name,
                    allow_root=bool(root_entries), progress=report, acknowledged=acknowledged)
            def completed(result):
                self.tool.organizer.refresh(False)
                QMessageBox.information(parent, "Source installation complete",
                    f"Created '{name}' with {len(result['mods'])} components.\nRestart MO2 to refresh its profile selector, then select the new profile.\n\nLock: {lock_path}")
            self.tool.run_job(parent, install, completed)
        self.tool.run_job(parent, plan, review)

    def open_restoration(self, parent, root, game):
        from .mo2_modlists.restoration import restoration_plan, restore_root
        operations = sorted(path.parent.name for path in (root / ".modlists").glob("*/journal.json"))
        if not operations:
            QMessageBox.information(parent, "Restore game files", "No import operations have been recorded in this instance.")
            return
        labels = []
        for operation in operations:
            journal = json.loads((root / ".modlists" / operation / "journal.json").read_text(encoding="utf-8-sig"))
            labels.append(f"{journal.get('profileName', 'Legacy import')} — {journal.get('status', 'unknown')} ({operation})")
        chosen, accepted = QInputDialog.getItem(parent, "Restore game files", "Installation operation:", labels, 0, False)
        if not accepted:
            return
        operation = operations[labels.index(chosen)]
        def review(plan):
            if plan["blockers"]:
                QMessageBox.warning(parent, "Restoration blocked", "\n".join(plan["blockers"]))
                return
            message = QMessageBox(QMessageBox.Icon.Warning, "Review game-file restoration",
                f"Restore {len(plan['files'])} physical files from '{plan['profile']}'.\n\n" + plan["notice"],
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel, parent)
            message.setTextFormat(Qt.TextFormat.PlainText)
            message.setDetailedText(json.dumps(plan, indent=2))
            if message.exec() != QMessageBox.StandardButton.Ok:
                return
            self.tool.run_job(parent, lambda report: restore_root(root, game, operation,
                reviewed_sha256=json_digest(plan), progress=report),
                lambda result: QMessageBox.information(parent, "Game files restored",
                    f"Restored {result['restoredFiles']} files. Profile and mod folders were preserved.\n"
                    "Install the lock into a new profile to deploy its root files again."))
        self.tool.run_job(parent, lambda report: restoration_plan(root, game, operation), review)

    def open_url(self, parent, root, game):
        from .mo2_modlists.url_manifest import nexus_url_kind, manifest_from_url
        url, accepted = QInputDialog.getText(parent, "Nexus URL to manifest", "Nexus mod or Collection URL:")
        if not accepted or not url.strip():
            return
        try:
            kind = nexus_url_kind(url)
        except PackError as exc:
            QMessageBox.warning(parent, "Invalid Nexus URL", str(exc))
            return
        if kind == "collection":
            self.open_collection(parent, root, game, source_url=url)
            return
        name, accepted = QInputDialog.getText(parent, "Manifest name", "Mod or pack name:")
        if not accepted or not name.strip():
            return
        filename, _ = QFileDialog.getSaveFileName(parent, "Save source manifest", "modlist.json", "Manifest (*.json)")
        if not filename:
            return
        def saved(document):
            choice = QMessageBox.question(parent, "Manifest saved", "Install this manifest into a new profile now?")
            if choice == QMessageBox.StandardButton.Yes:
                self.open_manifest(parent, root, game, filename)
        from .mo2_modlists.credentials import headers
        self.tool.run_job(parent, lambda report: manifest_from_url(url, Path(filename), name=name,
            headers=headers("nexus"), ask=self.ask, progress=report), saved)

    def open_collection(self, parent, root, game, source_url=None):
        from .mo2_modlists.collections import (read_collection, fetch_collection, convert_collection, write_collection_manifest,
                                             bundled_dependency, installer_fields, entry_source, handoff_complete)
        choice, accepted = ("Nexus Collection URL", True) if source_url else QInputDialog.getItem(parent, "Import Nexus Collection", "Collection source:",
            ["Downloaded collection package", "Nexus Collection URL"], 0, False)
        if not accepted:
            return
        if choice == "Nexus Collection URL":
            source, accepted = (source_url, True) if source_url else QInputDialog.getText(parent, "Nexus Collection", "Collection URL or NXM revision link:")
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
                from .mo2_modlists.credentials import headers
                path, identity = fetch_collection(source, root / ".modlists/source-cache", progress=report, headers=headers("nexus"))
            else:
                path, identity = Path(source), None
                if path.suffix.lower() == ".json":
                    possible = json.loads(path.read_text(encoding="utf-8-sig"))
                    if "retainedInstructions" in possible:
                        if json_digest(possible["retainedInstructions"]) != possible.get("collectionSha256"):
                            raise PackError("Saved Collection review metadata changed")
                        identity = possible.get("manifest", {}).get("extensions", {}).get("nexusCollection", {}).get("identity")
                        return possible["retainedInstructions"], identity, possible.get("decisions", {}), None
            return read_collection(path), identity, {}, path if path.suffix.lower() != ".json" else None
        def review(loaded):
            from .mo2_modlists.manifest import local_dependency, source_from_url
            document, identity, decisions, package_path = loaded
            collection_sha = json_digest(document)
            versions = document["info"].get("gameVersions") or []
            if len(versions) > 1 and "gameVersion" not in decisions.get("_collection", {}):
                version, accepted = QInputDialog.getItem(parent, "Collection game version", "Target game version:", versions, 0, False)
                if not accepted:
                    return
                decisions.setdefault("_collection", {})["gameVersion"] = version
            for index, mod in enumerate(document["mods"], 1):
                alias = f"mod-{index:04d}"
                decision = decisions.setdefault(alias, {})
                if mod.get("optional") and "include" not in decision:
                    answer = QMessageBox.question(parent, "Optional collection mod", "Include " + mod.get("name", str(index)) + "?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
                    if answer == QMessageBox.StandardButton.Cancel:
                        return
                    decision["include"] = answer == QMessageBox.StandardButton.Yes
                if decision.get("include") is False:
                    continue
                known_source = entry_source(mod, decision, document["info"]["domainName"])
                unsupported = installer_fields(mod)
                if unsupported and not handoff_complete(decision, known_source, unsupported, collection_sha):
                    message = QMessageBox(parent)
                    message.setWindowTitle("Installer handoff — " + mod.get("name", alias))
                    message.setText("This entry has installer choices, patches or instructions that need an explicit handoff.\n"
                        "Supply a prepared ZIP/7z containing the completed output and a recipe describing that archive, or retain this entry as unresolved.")
                    message.setDetailedText(json.dumps({key: mod[key] for key in unsupported}, indent=2))
                    prepare = message.addButton("Use prepared archive…", QMessageBox.ButtonRole.ActionRole)
                    unresolved = message.addButton("Keep unresolved", QMessageBox.ButtonRole.ActionRole)
                    message.addButton(QMessageBox.StandardButton.Cancel)
                    message.exec()
                    if message.clickedButton() == unresolved:
                        continue
                    if message.clickedButton() != prepare:
                        return
                    archive, _ = QFileDialog.getOpenFileName(parent, "Prepared installer output", "", "Archives (*.zip *.7z)")
                    if not archive:
                        return
                    recipe, _ = QFileDialog.getOpenFileName(parent, "Recipe for prepared archive", "", "Recipe (*.json)")
                    if not recipe:
                        return
                    note, accepted = QInputDialog.getText(parent, "Record completed handoff",
                        "Describe how you applied all listed installer choices, patches and instructions to this archive:")
                    if not accepted or not note.strip():
                        return
                    decision.update(localSelection=archive, recipe=Path(recipe).resolve().as_posix(), handoff={
                        "method": "prepared-archive", "collectionSha256": collection_sha, "handled": unsupported, "note": note})
                elif known_source is None:
                    if mod.get("source", {}).get("type") == "bundle" and package_path:
                        continue  # Extract the exact embedded archive in the worker.
                    source_kind, accepted = QInputDialog.getItem(parent, "Source for " + mod.get("name", alias),
                        "Provide a supported source for this Collection entry:", ["Local archive", "Nexus/GitHub URL", "Keep unresolved"], 0, False)
                    if not accepted:
                        return
                    if source_kind == "Local archive":
                        archive, _ = QFileDialog.getOpenFileName(parent, "Source archive", "", "Archives (*.zip *.7z)")
                        if not archive:
                            return
                        decision["localSelection"] = archive
                    elif source_kind == "Nexus/GitHub URL":
                        url, accepted = QInputDialog.getText(parent, "Source URL", "Nexus file page or exact GitHub release asset URL:")
                        if not accepted:
                            return
                        try:
                            decision["source"] = source_from_url(url)
                        except PackError as exc:
                            QMessageBox.warning(parent, "Source URL", str(exc))
                            return
            def convert(report):
                for index, mod in enumerate(document["mods"], 1):
                    alias = f"mod-{index:04d}"
                    decision = decisions[alias]
                    if (package_path and mod.get("source", {}).get("type") == "bundle"
                        and decision.get("include") is not False and "source" not in decision and "localSelection" not in decision):
                        decision.update(bundled_dependency(package_path, mod, root / ".modlists/source-cache", report))
                for alias, decision in decisions.items():
                    if "localSelection" in decision:
                        report("Verifying Collection source " + alias)
                        decision.update(local_dependency(Path(decision.pop("localSelection")), destination))
                return convert_collection(document, identity=identity, decisions=decisions)
            self.tool.run_job(parent, convert, save_draft)
        def save_draft(draft):
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
