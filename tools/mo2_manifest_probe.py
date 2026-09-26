"""Disposable MO2 host test for the real manifest-export dialog flow."""
import json
import os
from pathlib import Path
import traceback
from unittest.mock import patch

import mobase
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox


class Probe(mobase.IPlugin):
    def name(self): return "Manifest export integration probe"
    def author(self): return "MO2 Modlists tests"
    def description(self): return "Test-only local/URL/skip export flow"
    def version(self): return mobase.VersionInfo(0, 1, 0)
    def settings(self): return []

    def init(self, organizer):
        self.organizer = organizer
        output = os.environ.get("MO2_MANIFEST_PROBE_OUTPUT")
        if output:
            self.output = Path(output)
            organizer.onUserInterfaceInitialized(lambda parent: QTimer.singleShot(500, lambda: self.run(parent)))
        return True

    def run(self, parent):
        self.output.mkdir(parents=True, exist_ok=True)
        report = {"sourceChoices": [], "messages": []}
        original_exec = QMessageBox.exec
        try:
            from mo2_modlists_plugin.plugin import ModlistsTool
            from mo2_modlists_plugin.mo2_modlists.manifest import validate_manifest
            tool = ModlistsTool()
            tool.init(self.organizer)
            tool.setParentWidget(parent)
            root, game, profile = tool.paths()
            def choose(dialog):
                title = dialog.windowTitle()
                if title.startswith("Choose source"):
                    label = "Local archive…" if "UnknownLocal" in title else "Source URL…" if "UnknownUrl" in title else "Skip mod"
                    report["sourceChoices"].append(label)
                    button = next(b for b in dialog.buttons() if b.text() == label)
                    QTimer.singleShot(0, button.click)
                return original_exec(dialog)
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(self.output / "modlist.json"), "")), \
                 patch.object(QFileDialog, "getOpenFileName", return_value=(str(self.output.parent / "fixture.zip"), "")), \
                 patch.object(QInputDialog, "getText", return_value=("https://github.com/example/mod/releases/download/v1/mod.zip", True)), \
                 patch.object(QMessageBox, "exec", choose), \
                 patch.object(QMessageBox, "information", side_effect=lambda *a: report["messages"].append(a[2])):
                tool.export_clicked(parent, root, game, profile)
            manifest = validate_manifest(json.loads((self.output / "modlist.json").read_text()))
            report["dependencies"] = manifest["dependencies"]
            report["onlyManifestExported"] = [p.name for p in self.output.iterdir()] == ["modlist.json"]
            report["success"] = report["onlyManifestExported"] and len(manifest["dependencies"]) == 3 and len(report["sourceChoices"]) == 3
        except Exception:
            report["error"] = traceback.format_exc()
        (self.output / "probe-result.json").write_text(json.dumps(report, indent=2))
        QApplication.quit()


def createPlugin():
    return Probe()
