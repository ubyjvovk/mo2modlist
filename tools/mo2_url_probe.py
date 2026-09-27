"""Opt-in MO2 host test of URL conversion, using the configured Nexus credential."""
import json
import os
from pathlib import Path
import traceback
from unittest.mock import patch

import mobase
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox


class Probe(mobase.IPlugin):
    def name(self): return "Modlists URL acceptance probe"
    def author(self): return "MO2 Modlists tests"
    def description(self): return "Opt-in source URL conversion test"
    def version(self): return mobase.VersionInfo(0, 1, 0)
    def settings(self): return []

    def init(self, organizer):
        self.organizer = organizer
        output = os.environ.get("MO2_URL_PROBE_OUTPUT")
        if output:
            self.output = Path(output)
            organizer.onUserInterfaceInitialized(lambda parent: QTimer.singleShot(500, lambda: self.run(parent)))
        return True

    def run(self, parent):
        result = {"errors": []}
        try:
            from mo2_modlists_plugin.plugin import ModlistsTool
            tool = ModlistsTool()
            tool.init(self.organizer)
            tool.setParentWidget(parent)
            root, game, profile = tool.paths()
            before = sorted(p.name for p in (root / "profiles").iterdir())
            target = self.output / "host-modlist.json"
            original_exec = QMessageBox.exec
            def message(dialog):
                if dialog.icon() == QMessageBox.Icon.Critical:
                    result["errors"].append(dialog.detailedText() or dialog.text())
                    QTimer.singleShot(0, dialog.accept)
                return original_exec(dialog)
            with patch.object(QInputDialog, "getText", side_effect=[
                ("https://www.nexusmods.com/cyberpunk2077/mods/32203", True),
                ("Immersive Third Person", True)]), \
                patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")), \
                patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No), \
                patch.object(QMessageBox, "exec", message):
                tool.importer.open_url(parent, root, game)
            document = json.loads(target.read_text(encoding="utf-8"))
            assert len(document["dependencies"]) == 7
            assert all("fileId" in dep["source"] for dep in document["dependencies"].values())
            assert before == sorted(p.name for p in (root / "profiles").iterdir())
            result.update(success=True, dependencies=7, unchangedProfiles=before)
        except Exception:
            result["error"] = traceback.format_exc()
        (self.output / "host-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        QApplication.quit()


def createPlugin(): return Probe()
