from __future__ import annotations
from typing import Optional, Tuple, List, Union, cast, Callable, Any, Dict, Sequence, TYPE_CHECKING

import atexit
import errno
import os
import shutil
from functools import wraps

from ocrd import Resolver
from ocrd_browser.model.page import Page
from ocrd_browser.util.file_groups import best_file_group, FileGroupHandle, PatternList
from ocrd_browser.util.image import add_dpi_to_png_buffer
from ocrd_browser.util.streams import SilencedStreams
from ocrd_modelfactory import page_from_file
from ocrd_models.constants import NAMESPACES as NS
from ocrd_models import OcrdFile
from ocrd_utils import pushd_popd
from ocrd_utils.constants import MIME_TO_EXT
from ocrd_utils import getLogger

from pathlib import Path
from tempfile import mkdtemp
from datetime import datetime
from urllib.parse import urlparse, unquote
from PIL import Image

import cv2

if TYPE_CHECKING:
    from ocrd import Workspace
    from ocrd_models.ocrd_page_generateds import PcGtsType
    # noinspection PyProtectedMember
    from lxml.etree import ElementBase as Element, _ElementTree as ElementTree
    try:
        from numpy.typing import ArrayLike
    except ImportError:
        ArrayLike = Sequence[Sequence[int]]  # type: ignore[misc]


EventCallBack = Optional[Callable[[str, Any], None]]


def check_editable(func: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(func)
    def guard(self: 'Document', *args: List[Any], **kwargs: Dict[Any, Any]) -> Any:
        if self._editable is not True:
            raise PermissionError('Document is not editable, can not call  {}'.format(func.__qualname__))
        return_value = func(self, *args, **kwargs)
        return return_value

    return guard


class Document:
    temporary_workspaces: List[str] = []

    def __init__(self, workspace: Optional[Workspace], emitter: Optional[EventCallBack] = None, editable: bool = False,
                 original_url: str = None):
        self.workspace = workspace
        self.emitter = emitter
        self._original_url = original_url
        self._editable = editable
        self._empty = True
        self._modified = False
        if self.workspace:
            os.chdir(self.workspace.directory)

    @classmethod
    def create(cls, emitter: EventCallBack = None) -> Document:
        return cls(None, emitter=emitter)

    @classmethod
    def load(cls, mets_url: Union[Path, str] = None, emitter: EventCallBack = None) -> Document:
        """
        Load a project from an url as a readonly view

        If you want to modify the Workspace, use Document.clone instead
        """
        if not mets_url:
            return cls.create(emitter=emitter)
        mets_path = cls._to_path(mets_url)

        workspace = Resolver().workspace_from_url(str(mets_path), download=False)
        doc = cls(workspace, emitter=emitter, original_url=str(mets_url))
        doc._empty = False
        return doc

    @classmethod
    def clone(cls, mets_url: Union[Path, str], emitter: EventCallBack = None, editable: bool = True) -> Document:
        """
        Clones a project (mets.xml and all used files) to a temporary directory for editing
        """
        doc = cls(cls._clone_workspace(mets_url), emitter=emitter, editable=editable, original_url=str(mets_url))
        doc._empty = False
        return doc

    @classmethod
    def _clone_workspace(cls, mets_url: Union[Path, str]) -> Workspace:
        """
        Clones a workspace (mets.xml and all used files) to a temporary directory for editing
        """
        log = getLogger('ocrd_browser.model.document.Document._clone_workspace')
        mets_url = cls._strip_local(mets_url, disallow_remote=False)
        temporary_workspace = mkdtemp(prefix='browse-ocrd-clone-')
        cls.temporary_workspaces.append(temporary_workspace)
        # TODO download = False and lazy loading would be nice for responsiveness
        log.info("Cloning '%s' to '%s'", mets_url, temporary_workspace)
        workspace = Resolver().workspace_from_url(mets_url=mets_url, dst_dir=temporary_workspace, download=True)
        return workspace

    @check_editable
    def save(self, backup_directory: Union[bool, Path, str] = True) -> None:
        if not self._original_url:
            raise ValueError('Need an _original_url to save')
        self.save_as(self._original_url, backup_directory=backup_directory)

    def save_as(self, mets_url: Union[Path, str], backup_directory: Union[bool, Path, str] = True) -> None:
        log = getLogger('ocrd_browser.model.document.Document.save_as')
        mets_path = self._to_path(mets_url)

        workspace_directory = mets_path.parent
        if workspace_directory.exists():
            if backup_directory:
                if isinstance(backup_directory, bool):
                    backup_directory = self._derive_backup_directory(workspace_directory)
                shutil.move(str(workspace_directory), str(backup_directory))
            else:
                shutil.rmtree(str(workspace_directory))

        mets_basename = mets_path.name
        workspace_directory.mkdir(parents=True, exist_ok=True)
        self._emit('document_saving', 0, None)

        saved_space = Resolver().workspace_from_url(mets_url=self.workspace.mets_target, mets_basename=mets_basename,
                                                    download=False, clobber_mets=True, dst_dir=workspace_directory)
        saved_files = list(saved_space.mets.find_files())
        for n, f in enumerate(saved_files):
            f = saved_space.download_file(f)
            self._emit('document_saving', n / len(saved_files), f)

        self._emit('document_saving', 1, None)
        self._emit('document_saved', Document(saved_space, self.emitter))
        self._original_url = str(mets_path)
        self._modified = False
        log.info('Saved to %s', self._original_url)

    @property
    def directory(self) -> Path:
        """
        Get workspace directory as a Path object
        """
        return Path(self.workspace.directory) if self.workspace else None

    @property
    def mets_filename(self) -> str:
        """
        Gets the mets file name (e.g. "mets.xml")
        """
        return Path(self.workspace.mets_target).name if self.workspace else 'mets.xml'

    @property
    def baseurl_mets(self) -> str:
        """
        Gets the uri of the original mets file name
        """
        return str(self.workspace.baseurl) + '/' + self.mets_filename if self.workspace else None

    def path(self, other: Union[OcrdFile, Path, str]) -> Optional[Path]:
        """
        Resolves other relative to current workspace
        """
        if not self.directory:
            return None
        if isinstance(other, OcrdFile):
            return self.directory.joinpath(other.local_filename)
        elif isinstance(other, Path):
            return self.directory.joinpath(other)
        elif isinstance(other, str):
            return self.directory.joinpath(other)
        else:
            raise ValueError('Unsupported other of type {}'.format(type(other)))

    @property
    def _tree(self) -> Optional[ElementTree]:
        # noinspection PyProtectedMember
        return self.workspace.mets._tree if self.workspace else None

    def xpath(self, xpath: str) -> Any:
        return self._tree.getroot().xpath(xpath, namespaces=NS) if self.workspace else []

    @property
    def page_ids(self) -> List[str]:
        """
        List of page_ids in this workspace

        TODO: This is unsorted (or sorted in document order) use @ORDER attribute or keep document order in sync with the correct order

        @return: List[str]
        """
        # noinspection PyTypeChecker
        return cast(List[str], self.workspace.mets.physical_pages if self.workspace else [])

    @property
    def file_groups(self) -> List[FileGroupHandle]:
        """
        A list with the distinct file_group/mimetype pairs in this workspace

        @return: List[FileGroupHandle]
        """
        distinct_groups: Dict[FileGroupHandle, None] = {}
        # Using dict keys as a workaround for an ordered set
        for el in self.xpath('mets:fileSec/mets:fileGrp[@USE]/mets:file[@MIMETYPE]'):
            distinct_groups[FileGroupHandle(el.getparent().get('USE'), el.get('MIMETYPE'))] = None

        return list(distinct_groups.keys())

    @property
    def title(self) -> str:
        return str(self.workspace.mets.unique_identifier) if self.workspace and self.workspace.mets.unique_identifier else '<unnamed>'

    def get_file_index(self) -> Dict[str, OcrdFile]:
        """
        Return all OcrdFiles by file id and additionally augments the OcrdFile with static_page_id for fast(er) lookup

        Example:
        page17 = [file for file in file_index.values() if file.static_page_id == 'PHYS_0017']

        """
        log = getLogger('ocrd_browser.model.document.Document.get_file_index')
        file_index = {}
        if self.workspace:
            for file in self.workspace.mets.find_files():
                file.static_page_id = None
                file_index[file.ID] = file

        file_pointers: List[Element] = self.xpath(
            'mets:structMap[@TYPE="PHYSICAL"]/mets:div[@TYPE="physSequence"]/mets:div[@TYPE="page"]/mets:fptr')
        for file_pointer in file_pointers:
            file_id = file_pointer.get('FILEID')
            page_id = file_pointer.getparent().get('ID')
            if file_id in file_index:
                file_index[file_id].static_page_id = page_id
            else:
                log.warning("FILEID '%s' for PAGE '%s' not in mets:fileSec", file_id, page_id)

        return file_index

    def get_image_paths(self, file_group: FileGroupHandle) -> Dict[str, Path]:
        """
        Builds a Dict ID->Path for all page_ids fast

        More precisely:  fast = Faster than iterating over page_ids and using mets.get_physical_page_for_file for each entry
        """
        log = getLogger('ocrd_browser.model.document.Document.get_image_paths')
        image_paths = {}
        file_index = self.get_file_index()
        for page_id in self.page_ids:
            images = [image for image in file_index.values() if image.static_page_id == page_id and file_group.match(image)]
            if len(images) > 0:
                image_paths[page_id] = self.directory.joinpath(images[0].local_filename)
            else:
                log.warning('Found no images for PAGE %s and fileGrp %s', page_id, file_group)
                image_paths[page_id] = None
        return image_paths

    def get_default_image_group(self, preferred_image_file_groups: PatternList = None) -> Optional[FileGroupHandle]:
        return best_file_group(self.file_groups, preferred_image_file_groups, [r'image/.*'], cutoff=0)

    def get_unused_page_id(self, template_page_id: str = 'PAGE_{page_nr}') -> Tuple[str, int]:
        """
        Finds a page_nr that yields an unused page_id for the workspace and returns page_id, page_nr

        @param template_page_id: str
        @return: Tuple[str, int]
        """
        page_nr = len(self.page_ids) + 1
        page_ids = self.page_ids
        while page_nr < 9999:
            page_id = template_page_id.format(**{'page_nr': page_nr})
            if page_id not in page_ids:
                return page_id, page_nr
            page_nr += 1

        raise RuntimeError('No unused page_id found')

    def display_id_range(self, page_id: str, page_qty: int) -> List[str]:
        """
        Calculates an page_id range of size page_qty around page_id
        @param page_id:
        @param page_qty:
        @return:
        """
        if not page_id:
            return []
        try:
            index = self.page_ids.index(page_id)
        except ValueError:
            return []
        index = index - index % page_qty
        return self.page_ids[index:index + page_qty]

    def page_for_id(self, page_id: str, file_group: str) -> Optional['Page']:
        if not page_id:
            return None
        return Page(self, page_id, file_group)

    def files_for_page_id(self, page_id: str, file_group: str = None, mimetype: str = None) -> List[OcrdFile]:
        with pushd_popd(self.workspace.directory):
            files: List[OcrdFile] = self.workspace.mets.find_files(fileGrp=file_group, pageId=page_id,
                                                                   mimetype=mimetype)
            files = [self.workspace.download_file(file) for file in files]
            return files

    def page_for_file(self, page_file: OcrdFile) -> PcGtsType:
        # cd and silence Warning: Value "ocrd-cis-word-alignment" ... does not match xsd enumeration restriction on TextDataTypeSimpleType
        with pushd_popd(self.workspace.directory), SilencedStreams(False, True):
            return page_from_file(page_file)

    def resolve_image(self, image_file: OcrdFile) -> Image:
        with pushd_popd(self.workspace.directory):
            pil_image = Image.open(self.workspace.download_file(image_file).local_filename)
            # pil_image.load()
            return pil_image

    @check_editable
    def reorder(self, ordered_page_ids: List[str]) -> None:
        """
        Orders the pages in physSequence according to ordered_page_ids

        """
        log = getLogger('ocrd_browser.model.document.Document.reorder')
        old_page_ids = self.page_ids

        if set(old_page_ids) != set(ordered_page_ids):
            raise ValueError('page_ids do not match: missing in mets.xml: {} / missing in order: {}'.format(
                set(ordered_page_ids).difference(set(old_page_ids)),
                set(self.page_ids).difference(set(ordered_page_ids))
            ))
        log.info('Reordering %s to %s', old_page_ids, ordered_page_ids)
        page_sequence: Element = self.xpath('mets:structMap[@TYPE="PHYSICAL"]/mets:div[@TYPE="physSequence"]')[0]

        ordered_divs = []
        for page_id in ordered_page_ids:
            divs = page_sequence.xpath('mets:div[@TYPE="page"][@ID="%s"]' % page_id, namespaces=NS)
            if divs:
                ordered_divs.append(divs[0])
                page_sequence.remove(divs[0])

        if len(page_sequence) > 0:
            raise RuntimeError('page_sequence not empty, still has: {}'.format(page_sequence.getchildren()))

        for div in ordered_divs:
            page_sequence.append(div)

        old_to_new = dict(zip(old_page_ids, self.page_ids))
        self.workspace.mets._refresh_caches()
        self.save_mets()
        self._emit('document_changed', 'reordered', old_to_new)

    @check_editable
    def delete_images(self, page_id: str, file_group: str = 'OCR-D-IMG') -> List[OcrdFile]:
        image_files: List[OcrdFile] = list(self.workspace.mets.find_files(pageId=page_id, fileGrp=file_group,
                                                                          local_only=True, mimetype='//image/.+'))

        for image_file in image_files:
            self.workspace.remove_file(image_file, force=True, keep_file=False, page_recursive=True,
                                       page_same_group=True)
        self.save_mets()
        self._emit('document_changed', 'page_changed', [page_id])
        return image_files

    def save_mets(self) -> None:
        if not self._editable:
            raise PermissionError('Can not modify Document with _editable == False')
        self.workspace.save_mets()
        self._modified = True

    @check_editable
    def delete_page(self, page_id: str) -> None:
        files = self.workspace.mets.find_files(pageId=page_id, local_only=True)
        for file in files:
            self.workspace.remove_file(file, force=False, keep_file=False)
        self.workspace.mets.remove_physical_page(page_id)
        self.save_mets()
        self._emit('document_changed', 'page_deleted', [page_id])

    @check_editable
    def add_image(self, image: ArrayLike, page_id: str, file_id: str, file_group: str = 'OCR-D-IMG', dpi: int = 300,
                  mimetype: str = 'image/png') -> OcrdFile:
        extension = MIME_TO_EXT[mimetype]
        retval, image_array = cv2.imencode(extension, image)
        image_bytes = add_dpi_to_png_buffer(image_array.tostring(), dpi)
        local_filename = Path(file_group, '%s%s' % (file_id, extension))
        current_file = self.workspace.add_file(file_group, ID=file_id, mimetype=mimetype, force=True,
                                               content=image_bytes,
                                               local_filename=str(local_filename), pageId=page_id)
        self._empty = False
        self.save_mets()
        self._emit('document_changed', 'page_added', [page_id])
        return current_file

    @property
    def modified(self) -> bool:
        return self._modified

    @property
    def empty(self) -> bool:
        return self._empty

    @property
    def original_url(self) -> str:
        return self._original_url

    @property
    def editable(self) -> bool:
        return self._editable

    @editable.setter
    def editable(self, editable: bool) -> None:
        if editable:
            if self._original_url:
                self.workspace = self._clone_workspace(self._original_url)
            else:
                # noinspection PyTypeChecker
                self.workspace = Resolver().workspace_from_nothing(directory=None, mets_basename='mets.xml')
        else:
            self.workspace = Resolver().workspace_from_url(self.baseurl_mets)
        self._editable = editable
        # self._empty = False
        # self._modified = False

    def _emit(self, event: str, *args: Any) -> None:
        if self.emitter is not None:
            self.emitter(event, *args)

    @staticmethod
    def _strip_local(mets_url: Union[Path, str], disallow_remote: bool = True) -> str:
        result = urlparse(str(mets_url))
        if result.scheme == 'file' or result.scheme == '':
            mets_url = unquote(result.path)
        elif disallow_remote:
            raise ValueError('invalid url {}'.format(mets_url))
        return str(mets_url)

    @staticmethod
    def _to_path(mets_url: Union[Path, str]) -> Path:
        result = urlparse(str(mets_url))
        if not (result.scheme == 'file' or result.scheme == ''):
            raise ValueError('invalid local path/url {}'.format(mets_url))
        return Path(unquote(result.path))

    @staticmethod
    def _derive_backup_directory(workspace_directory: Path, now: datetime = None) -> Path:
        now = now or datetime.now()
        return workspace_directory.parent / ('.bak.' + workspace_directory.name + '.' + now.strftime('%Y%m%d-%H%M%S'))

    @classmethod
    def delete_temporary_workspaces(cls) -> None:
        for temporary_workspace in cls.temporary_workspaces:
            try:
                shutil.rmtree(temporary_workspace)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise


atexit.register(Document.delete_temporary_workspaces)
