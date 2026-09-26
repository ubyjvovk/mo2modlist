"""Test-only MO2 plugin: exercise the real tool/Qt worker without desktop input.

Copy only into a disposable instance. Set MO2_MODLISTS_PROBE_OUTPUT to an empty
artifact directory when launching that instance. Never shipped in the extension.
"""
import json
import os
from pathlib import Path
import sys
import traceback

import mobase
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication


class Probe(mobase.IPlugin):
    def name(self): return "Modlists integration probe"
    def author(self): return "MO2 Modlists tests"
    def description(self): return "Disposable-instance integration test"
    def version(self): return mobase.VersionInfo(0, 1, 0)
    def settings(self): return []

    def init(self, organizer):
        self.organizer = organizer
        destination = os.environ.get("MO2_MODLISTS_PROBE_OUTPUT")
        if destination:
            self.destination = Path(destination)
            organizer.onUserInterfaceInitialized(lambda parent: QTimer.singleShot(1000, lambda: self.run(parent)))
        return True

    def run(self, parent):
        self.destination.mkdir(parents=True, exist_ok=True)
        report = {}
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from mo2_modlists_plugin.plugin import ModlistsTool
            from mo2_modlists_plugin.mo2_modlists.core import export_profile, import_profile
            tool = ModlistsTool()
            tool.init(self.organizer)
            tool.setParentWidget(parent)
            root, game, profile = tool.paths()
            report.update(instance=str(root), game=str(game), profile=profile, python=sys.version,
                          downloadManager=hasattr(self.organizer, "downloadManager"),
                          refresh=hasattr(self.organizer, "refresh"))
            # Persist milestones even if an unexpected dialog interrupts the probe.
            def checkpoint():
                (self.destination / "result.json").write_text(json.dumps(report, indent=2))

            def inspect_dialog():
                dialog = QApplication.activeModalWidget()
                report["dialogTitle"] = dialog.windowTitle() if dialog else None
                if dialog:
                    dialog.accept()

            QTimer.singleShot(250, inspect_dialog)
            tool.display()
            checkpoint()
            bundle = self.destination / "export"
            tool.run_job(parent, lambda progress: export_profile(root, game, profile, bundle, progress=progress),
                         lambda result: report.update(export=result))
            checkpoint()
            tool.run_job(parent, lambda progress: import_profile(bundle, root, game, "Probe - " + self.destination.name, allow_root=True, progress=progress, manage_ini=False),
                         lambda result: report.update(importResult=result))
            self.organizer.refresh(False)
            report["success"] = bool(report.get("export") and report.get("importResult") and report.get("dialogTitle"))
        except Exception:
            report["error"] = traceback.format_exc()
        (self.destination / "result.json").write_text(json.dumps(report, indent=2))
        QApplication.quit()


def createPlugin():
    return Probe()
