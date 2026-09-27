"""Opt-in real-host download probe; uses MO2's existing supported Nexus service."""
import json, os
from pathlib import Path
import mobase
from PyQt6.QtCore import QTimer
class Probe(mobase.IPlugin):
 def name(self): return 'Modlists Nexus download acceptance'
 def author(self): return 'MO2 Modlists tests'
 def description(self): return 'Opt-in real Nexus acquisition test'
 def version(self): return mobase.VersionInfo(0,1,0)
 def settings(self): return []
 def init(self,o):
  self.o=o
  self.output=os.environ.get('MO2_NEXUS_DOWNLOAD_PROBE')
  if self.output:
   o.onUserInterfaceInitialized(lambda p: QTimer.singleShot(750,self.run))
  return True
 def save(self,**data):
  Path(self.output).write_text(json.dumps(data,indent=2),encoding='utf-8')
 def run(self):
  self.manager=self.o.downloadManager()
  self.manager.onDownloadComplete(self.complete)
  self.manager.onDownloadFailed(self.failed)
  self.did=self.manager.startDownloadNexusFile(32203,161480)
  self.save(status='started' if self.did>=0 else 'not-started',downloadId=self.did,modId=32203,fileId=161480)
 def complete(self,did):
  if did==self.did: self.save(status='complete',downloadId=did,path=self.manager.downloadPath(did),modId=32203,fileId=161480)
 def failed(self,did):
  if did==self.did: self.save(status='failed',downloadId=did,modId=32203,fileId=161480)
def createPlugin(): return Probe()
