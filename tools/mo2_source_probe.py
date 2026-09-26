"""Real MO2 host test for source resolution, review, installation and lock reuse."""
import json
import os
from pathlib import Path
import traceback
from unittest.mock import patch

import mobase
from PyQt6.QtCore import QTimer, QThread
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox


class Probe(mobase.IPlugin):
    def name(self): return "Source installation integration probe"
    def author(self): return "MO2 Modlists tests"
    def description(self): return "Disposable source-manifest importer integration test"
    def version(self): return mobase.VersionInfo(0, 1, 0)
    def settings(self): return []

    def init(self, organizer):
        self.organizer = organizer
        output = os.environ.get("MO2_SOURCE_PROBE_OUTPUT")
        if output:
            self.output = Path(output)
            organizer.onUserInterfaceInitialized(lambda parent: QTimer.singleShot(500, lambda: self.run(parent)))
        return True

    def run(self, parent):
        report = {"messages": [], "reviews": 0, "uiThreadChoices": []}
        collection_mode = os.environ.get("MO2_SOURCE_PROBE_COLLECTION") == "1"
        original_exec = QMessageBox.exec
        try:
            from mo2_modlists_plugin.plugin import ModlistsTool
            from mo2_modlists_plugin.mo2_modlists.core import digest
            tool = ModlistsTool()
            tool.init(self.organizer)
            tool.setParentWidget(parent)
            root, game, current = tool.paths()
            before = digest(root / "profiles" / current / "modlist.txt")
            def choose_file(*args, **kwargs):
                if args[1] == "Full collection package":
                    return str(self.output / "collection.zip"), ""
                report["uiThreadChoices"].append(QThread.currentThread() == QApplication.instance().thread())
                return str(self.output / "fixture.recipe.json"), ""
            def choose(dialog):
                if dialog.windowTitle() == "Review source installation":
                    report["reviews"] += 1
                    report["reviewDetails"] = dialog.detailedText()
                    QTimer.singleShot(0, lambda: dialog.done(QMessageBox.StandardButton.Ok))
                elif dialog.windowTitle() == "Required Collection instructions":
                    report["instructionAcknowledgements"] = report.get("instructionAcknowledgements", 0) + 1
                    QTimer.singleShot(0, lambda: dialog.done(QMessageBox.StandardButton.Yes))
                elif dialog.icon() == QMessageBox.Icon.Critical:
                    report["messages"].append(dialog.detailedText() or dialog.text())
                    QTimer.singleShot(0, dialog.accept)
                return original_exec(dialog)
            def run(name):
                with patch.object(QFileDialog, "getOpenFileName", side_effect=choose_file), \
                     patch.object(QFileDialog, "getSaveFileName", return_value=(str(self.output / "modlist.json"), "")), \
                     patch.object(QInputDialog, "getItem", return_value=("Downloaded collection package", True)), \
                     patch.object(QInputDialog, "getText", return_value=(name, True)), \
                     patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No), \
                     patch.object(QMessageBox, "exec", choose), \
                     patch.object(QMessageBox, "information", side_effect=lambda *a: report["messages"].append(a[2])):
                    if collection_mode and "firstMods" not in report:
                        tool.importer.open_collection(parent, root, game)
                    else:
                        tool.importer.open_manifest(parent, root, game, str(self.output / "modlist.json"))
                profile = root / "profiles" / name
                lines = (profile / "modlist.txt").read_text(encoding="utf-8-sig").splitlines()
                mods = [line[1:] for line in lines if line.startswith("+")]
                assert len(mods) == 1
                assert (root / "mods" / mods[0] / "r6/scripts/modlists_probe.txt").read_text() == "source importer fixture"
                return mods
            report["firstMods"] = run(self.output.name + " First")
            (self.output / "fixture.zip").rename(self.output / "fixture.zip.saved")
            (self.output / "fixture.recipe.json").rename(self.output / "fixture.recipe.json.saved")
            report["cachedMods"] = run(self.output.name + " Cached")
            assert report["firstMods"] != report["cachedMods"]
            assert digest(root / "profiles" / current / "modlist.txt") == before
            assert report["reviews"] == 2
            assert report["uiThreadChoices"] == [True]
            if collection_mode:
                assert report["instructionAcknowledgements"] == 2
                manifest = json.loads((self.output / "modlist.json").read_text(encoding="utf-8"))
                assert len(manifest["dependencies"]) == 1
                assert "nexusBundledArtifact" in manifest["dependencies"]["mod-0001"]["extensions"]
            report["success"] = True
        except Exception:
            report["error"] = traceback.format_exc()
        (self.output / "probe-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        QApplication.quit()


def createPlugin():
    return Probe()
