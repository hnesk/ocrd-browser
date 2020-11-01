import shlex
from subprocess import Popen
from typing import Dict, Optional

from ocrd_models import OcrdFile
from ocrd_utils import getLogger

from ocrd_browser.model import Document
from ocrd_browser.util.config import _Tool, SETTINGS


class ResolvableFileName:
    def __init__(self, filename, in_doc: Document):
        self.filename = filename
        self.in_doc = in_doc

    @property
    def absolute(self):
        return shlex.quote(str(self.in_doc.path(self.filename).absolute()))

    @property
    def relative(self):
        return shlex.quote(self.filename)

    def __str__(self):
        return self.absolute


class QuotingProxy:
    def __init__(self, object_):
        self.object = object_

    def __getattr__(self, item):
        if hasattr(self.object, item):
            return shlex.quote(getattr(self.object, item))
        else:
            raise AttributeError("Unknown attribute '{}' on {} ".format(item, self.object))


class FileProxy(QuotingProxy):
    def __init__(self, file: OcrdFile, in_doc: Document):
        super().__init__(file)
        self.in_doc = in_doc

    @property
    def local_filename(self) -> ResolvableFileName:
        return ResolvableFileName(self.object.local_filename, self.in_doc)

    # Recommended alias path, because local_filename sounds like a relative path
    path = local_filename


class Launcher:
    def __init__(self, tools: Optional[Dict[str, _Tool]] = None):
        self.tools = tools if tools else SETTINGS.tools

    def launch(self, toolname: str, doc: Document, file: OcrdFile) -> Optional[Popen]:
        if toolname in self.tools:
            return self.launch_tool(self.tools[toolname], doc, file)
        else:
            log = getLogger('ocrd_browser.util.launcher.Launcher.launch')
            log.error(
                'Tool "%s" not found in your config, to fix place the following section in your ocrd-browser.conf',
                toolname)
            log.error('[Tool %s]', toolname)
            log.error('commandline = /usr/bin/yourtool --base-dir {workspace.directory} {file.path.absolute}')
            return None

    def launch_tool(self, tool: _Tool, doc: Document, file: OcrdFile, **kwargs) -> Popen:
        log = getLogger('ocrd_browser.util.launcher.Launcher.launch_tool')
        commandline = self._template(tool.commandline, doc, file)
        log.debug('Calling tool "%s" with commandline: ', tool.name)
        log.debug('%s', commandline)
        process = Popen(args=commandline, shell=True, cwd=doc.directory, **kwargs)
        return process

    def _template(self, arg: str, doc: Document, file: OcrdFile):
        return arg.format(file=FileProxy(file, doc), workspace=QuotingProxy(doc.workspace))
