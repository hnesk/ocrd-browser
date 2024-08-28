from pathlib import Path
from tempfile import TemporaryDirectory

from ocrd_browser.util.file_groups import FileGroupHandle
from tests import TestCase, ASSETS_PATH, TEST_BASE_PATH
from ocrd_browser.model import Document, Page
from datetime import datetime
from ocrd_models.ocrd_page import PcGtsType


# TODO: Later: from tests.assets import Assets, copy_of_directory

class DocumentTestCase(TestCase):

    def setUp(self):
        self.path = ASSETS_PATH / 'kant_aufklaerung_1784/data/mets.xml'

    def test_get_page_ids(self):
        doc = Document.load(self.path)
        self.assertEqual(['PHYS_0017', 'PHYS_0020'], doc.page_ids)

    def test_get_file_groups(self):
        doc = Document.load(self.path)
        expected = [
            FileGroupHandle('OCR-D-IMG', 'image/tiff'),
            FileGroupHandle('OCR-D-GT-PAGE', 'application/vnd.prima.page+xml'),
            FileGroupHandle('OCR-D-GT-ALTO', 'application/alto+xml')
        ]
        self.assertEqual(expected, doc.file_groups)

    def test_get_page_index(self):
        doc = Document.load(self.path)
        file_index = doc.get_file_index()
        page17 = [file for file in file_index.values() if file.static_page_id == 'PHYS_0017']
        alto = [file for file in file_index.values() if file.mimetype == 'application/alto+xml']
        self.assertEqual(3, len(page17))
        self.assertEqual(2, len(alto))

    def test_get_image_paths(self):
        doc = Document.load(self.path)
        image_paths = doc.get_image_paths(FileGroupHandle('OCR-D-IMG', 'image/tiff'))
        self.assertEqual(2, len(image_paths))
        self.assertEqual('INPUT_0017.tif', image_paths['PHYS_0017'].name)
        self.assertEqual('INPUT_0020.tif', image_paths['PHYS_0020'].name)

    def test_get_image_paths_only_returns_matching_groups(self):
        """
        Testcase for https://github.com/hnesk/browse-ocrd/issues/51
        """
        doc = Document.load(ASSETS_PATH / '../example/workspaces/kant_aufklaerung_1784_bin/mets.xml')
        image_paths = doc.get_image_paths(FileGroupHandle('OCR-D-IMG-BIN', 'image/png'))
        self.assertEqual(2, len(image_paths))
        self.assertEqual('OCR-D-IMG-BIN_0001.IMG-BIN.png', image_paths['PHYS_0017'].name)
        self.assertEqual('OCR-D-IMG-BIN_0002.IMG-BIN.png', image_paths['PHYS_0020'].name)

    def test_get_default_image_group(self):
        doc = Document.load(ASSETS_PATH / 'kant_aufklaerung_1784-complex/data/mets.xml')
        file_group = doc.get_default_image_group(['OCR-D-IMG-BIN', 'OCR-D-IMG.*'])
        self.assertEqual(FileGroupHandle('OCR-D-IMG-BIN', 'image/png'), file_group)

    def test_get_default_image_group_no_preference(self):
        doc = Document.load(ASSETS_PATH / 'kant_aufklaerung_1784-complex/data/mets.xml')
        file_group = doc.get_default_image_group()
        self.assertEqual(FileGroupHandle('OCR-D-IMG', 'image/tiff'), file_group)

    def test_get_default_image_group_with_missing_ocr_d_img(self):
        doc = Document.load(ASSETS_PATH / '../example/workspaces/no_ocrd_d_img_group/mets.xml')
        file_group = doc.get_default_image_group()
        self.assertEqual(FileGroupHandle('OCR-D-IMG-PNG', 'image/png'), file_group)

    def test_path_string(self):
        doc = Document.load(self.path)
        self.assertEqual(ASSETS_PATH / 'kant_aufklaerung_1784/data/lala.xml', doc.path('lala.xml'))

    def test_path_path(self):
        doc = Document.load(self.path)
        self.assertEqual(ASSETS_PATH / 'kant_aufklaerung_1784/data/OCR-D-DIR/lala.xml',
                         doc.path(Path('OCR-D-DIR/lala.xml')))

    def test_path_ocrd_file(self):
        doc = Document.load(self.path)
        image_file = list(doc.workspace.mets.find_files(pageId='PHYS_0017', fileGrp='OCR-D-IMG'))[0]
        self.assertEqual(ASSETS_PATH / 'kant_aufklaerung_1784/data/OCR-D-IMG/INPUT_0017.tif', doc.path(image_file))

    def test_reorder(self):
        doc = Document.clone(self.path)
        doc.reorder(['PHYS_0020', 'PHYS_0017'])
        self.assertEqual(['PHYS_0020', 'PHYS_0017'], doc.page_ids)

    def test_reorder_with_wrong_ids_raises_value_error(self):
        doc = Document.clone(self.path)
        with self.assertRaises(ValueError) as context:
            doc.reorder(['PHYS_0021', 'PHYS_0017'])

        self.assertIn('page_ids do not match', str(context.exception))

    def test_delete(self):
        doc = Document.clone(self.path)
        doc.delete_page('PHYS_0017')
        self.assertEqual(['PHYS_0020'], doc.page_ids)

    def test_clone(self):
        doc = Document.clone(self.path)
        self.assertIn('browse-ocrd-clone-', doc.workspace.directory)
        self.assertEqual(str(self.path), doc.baseurl_mets)

        original_files = self.path.parent.rglob('*.*')
        cloned_files = Path(doc.workspace.directory).rglob('*.*')
        for original, cloned in zip(sorted(original_files), sorted(cloned_files)):
            self.assertEqual(original.read_bytes(), cloned.read_bytes())

    def test_save(self):
        doc = Document.clone(self.path)
        with TemporaryDirectory(prefix='browse-ocrd tests') as directory:
            saved_mets = directory + '/mets.xml'
            doc.save_as(saved_mets)
            saved = Document.load(saved_mets)
            self.assertEqual(doc.file_groups, saved.file_groups)
            self.assertEqual(doc.page_ids, saved.page_ids)
            self.assertEqual(doc.workspace.mets.unique_identifier, saved.workspace.mets.unique_identifier)

            for page_id in doc.page_ids:
                for fg in doc.file_groups:
                    original_file = doc.files_for_page_id(page_id, fg.group, fg.mime)[0]
                    # workaround for core#1149: remove .url absolute path from cloning
                    original_file.url = None
                    # workaround for core#1226: remove URL FLocat directly
                    flocat = original_file._el.find('{http://www.loc.gov/METS/}FLocat[@LOCTYPE="URL"]')
                    if flocat is not None:
                        original_file._el.remove(flocat)
                    saved_file = saved.files_for_page_id(page_id, fg.group, fg.mime)[0]
                    self.assertEqual(original_file, saved_file)

    def test_derive_backup_directory(self):
        self.assertEqual(
            Path('/home/jk/.bak.important_project.20200813-184321'),
            Document._derive_backup_directory(Path('/home/jk/important_project'), datetime(2020, 8, 13, 18, 43, 21))
        )

    def test_page_for_id_with_no_images_for_page_and_fileGrp(self):
        """
        Issue #4: list index out of range on non-XML fileGrp

        https://github.com/hnesk/browse-ocrd/issues/4
        """
        doc = Document.load(ASSETS_PATH / 'kant_aufklaerung_1784-complex/data/mets.xml')
        page = doc.page_for_id('PHYS_0020', 'OCR-D-IMG-CLIP')
        self.assertIsNone(page.page_file)

    def test_page_for_id_with_nothing_for_page_and_fileGrp(self):
        """
        Issue #4 again: This time for missing PAGE-XMLs

        https://github.com/hnesk/browse-ocrd/issues/4
        """
        doc = Document.load(ASSETS_PATH / '../example/workspaces/kant_aufklaerung_1784_missing_xml/mets.xml')
        page = doc.page_for_id('PHYS_0020', 'OCR-D-GT-PAGE')
        self.assertIsNone(page.page_file)

    def test_page_for_id_with_multiple_images_for_page_and_fileGrp(self):
        """
        returns first image and warns
        """
        doc = Document.load(ASSETS_PATH / 'kant_aufklaerung_1784-complex/data/mets.xml')
        # with self.assertLogs('ocrd_browser.model.document', level='WARNING') as log_watch:
        page = doc.page_for_id('PHYS_0017', 'OCR-D-IMG-CLIP')
        self.assertIsInstance(page, Page)
        self.assertIsInstance(page.pc_gts, PcGtsType)
        # self.assertEqual(1, len(log_watch.records))
        # self.assertEqual("No PAGE-XML but 2 images for page 'PHYS_0017' in fileGrp 'OCR-D-IMG-CLIP'", log_watch.records[0].msg)

    def test_modify_when_not_editable(self):
        doc = Document.load(self.path)
        with self.assertRaises(PermissionError):
            doc.reorder(['PHYS_0020', 'PHYS_0017'])

    def test_modify_when_editable(self):
        doc = Document.clone(self.path)
        doc.reorder(['PHYS_0020', 'PHYS_0017'])

    def test_path_with_spaces(self):
        doc = Document.load((TEST_BASE_PATH / 'example/workspaces/heavy quoting/mets.xml').as_uri())
        page = doc.page_for_id('PHYS_0017', 'OCR-D-GT-PAGE')
        image = doc.workspace.image_from_page(page.page, 'PHYS_0017')
        # Assert no exceptions happened and a sensible return value
        self.assertGreater(image[0].height, 100)

    def test_missing_image(self):
        path = TEST_BASE_PATH / 'example/workspaces/kant_aufklaerung_1784_missing_image/mets.xml'
        uri = path.as_uri()
        doc = Document.load(uri)
        page = doc.page_for_id('PHYS_0017', 'OCR-D-GT-PAGE')
        image, info, exif = page.get_image(feature_selector='', feature_filter='binarized')
        # Assert no exceptions happened and no image returned
        self.assertIsNone(image)
