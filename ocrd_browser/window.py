import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GdkPixbuf, Gio, GObject, GLib, Pango

from ocrd_browser import __version__
from ocrd_browser.model import Document
from ocrd_browser.view import ViewRegistry, ViewImages, View
from ocrd_browser.icon_store import LazyLoadingListStore
from ocrd_browser.image_util import cv_scale, cv_to_pixbuf
from ocrd_browser.gtk_util import ActionRegistry
from pkg_resources import resource_filename

import cv2
import os


@Gtk.Template(filename=resource_filename(__name__, 'resources/main-window.ui'))
class MainWindow(Gtk.ApplicationWindow):
    __gtype_name__ = "MainWindow"

    header_bar: Gtk.HeaderBar = Gtk.Template.Child()
    page_list_scroller: Gtk.ScrolledWindow = Gtk.Template.Child()
    panes: Gtk.Paned = Gtk.Template.Child()
    current_page_label: Gtk.Label = Gtk.Template.Child()
    view_container: Gtk.Box = Gtk.Template.Child()
    view_menu_box: Gtk.Box = Gtk.Template.Child()


    def __init__(self, **kwargs):
        Gtk.ApplicationWindow.__init__(self, **kwargs)
        self.set_icon(GdkPixbuf.Pixbuf.new_from_resource("/org/readmachine/ocrd-browser/icons/icon.png"))
        self.views = []
        self.current_page_id = None
        self.document = Document.create()

        vstring = GLib.Variant("s", "")

        self.actions = ActionRegistry(for_widget=self)
        self.actions.create('close')
        self.actions.create('goto_first')
        self.actions.create('go_back')
        self.actions.create('go_forward')
        self.actions.create('goto_last')
        self.actions.create('close_view', param_type=vstring)
        self.actions.create('create_view', param_type=vstring)

        self.page_list = PagePreviewList(self.document)
        self.page_list_scroller.add(self.page_list)
        self.page_list.connect('page_selected', self.page_selected)

        for id_, view in self.view_registry.get_view_options().items():
            menu_item = Gtk.ModelButton(visible=True,centered=False,halign=Gtk.Align.FILL,label = view, hexpand=True)
            menu_item.set_detailed_action_name('win.create_view("{}")'.format(id_))
            self.view_menu_box.pack_start(menu_item, True, True, 0)

        self.add_view(ViewImages)

        self.update_ui()



    @Gtk.Template.Callback()
    def on_recent_menu_item_activated(self, recent_chooser: Gtk.RecentChooserMenu):
        app = self.get_application()
        item: Gtk.RecentInfo = recent_chooser.get_current_item()
        app.open_in_window(item.get_uri(), window=self)


    def open(self, uri):
        self.set_title('Loading')
        self.header_bar.set_title('Loading ...')
        self.header_bar.set_subtitle(uri)
        self.update_ui()
        # Give GTK some break to show the Loading message
        GLib.timeout_add(50, self._open, uri)

    def _open(self, uri):
        self.document = Document.load(uri)
        self.page_list.set_document(self.document)

        title = self.document.workspace.mets.unique_identifier if self.document.workspace.mets.unique_identifier else '<unnamed>'
        self.set_title(title)
        self.header_bar.set_title(title)
        self.header_bar.set_subtitle(self.document.workspace.directory)

        for view in self.views:
            view.set_document(self.document)

        if len(self.document.page_ids):
            self.page_selected(None, self.document.page_ids[0])

    @property
    def view_registry(self) -> ViewRegistry:
        return self.get_application().view_registry

    def add_view(self, view_class):
        name = 'view_{}'.format(len(self.views))
        view: View = view_class(name)
        view.build()
        view.set_document(self.document)
        self.views.append(view)
        self.connect('page_activated', view.page_activated)
        self.view_container.pack_start(view.container, True, True, 3)

    def page_selected(self, _, page_id):
        if self.current_page_id != page_id:
            self.current_page_id = page_id
            self.emit('page_activated', page_id)

    @GObject.Signal(arg_types=(str,))
    def page_activated(self, page_id):
        index = self.document.page_ids.index(page_id)
        self.current_page_label.set_text('#{} ({}/{})'.format(page_id, index + 1, len(self.document.page_ids)))
        self.update_ui()
        pass

    def update_ui(self):
        can_go_back = False
        can_go_forward = False
        if self.current_page_id and len(self.document.page_ids) > 0:
            index = self.document.page_ids.index(self.current_page_id)
            last_page = len(self.document.page_ids) - 1
            can_go_back = index > 0
            can_go_forward = index < last_page

        self.actions['goto_first'].set_enabled(can_go_back)
        self.actions['go_back'].set_enabled(can_go_back)
        self.actions['go_forward'].set_enabled(can_go_forward)
        self.actions['goto_last'].set_enabled(can_go_forward)

    def on_close(self, _a: Gio.SimpleAction, _p):
        self.destroy()

    def on_goto_first(self, _a: Gio.SimpleAction, _p):
        self.page_list.goto_index(0)

    def on_go_forward(self, _a: Gio.SimpleAction, _p):
        self.page_list.skip(1)

    def on_go_back(self, _a: Gio.SimpleAction, _p):
        self.page_list.skip(-1)

    def on_goto_last(self, _a: Gio.SimpleAction, _p):
        self.page_list.goto_index(-1)

    def on_create_view(self, _a, selected_view_id: GLib.Variant):
        view_class = self.view_registry.get_view(selected_view_id.get_string())
        if view_class:
            self.add_view(view_class)

    def on_close_view(self, _action: Gio.SimpleAction, view_name: GLib.Variant):
        for view in self.views:
            if view.name == view_name.get_string():
                view.container.destroy()
                break
        self.disconnect_by_func(view.page_activated)
        self.views.remove(view)
        del view


@Gtk.Template(filename=resource_filename(__name__, 'resources/about-dialog.ui'))
class AboutDialog(Gtk.AboutDialog):
    __gtype_name__ = "AboutDialog"

    def __init__(self, **kwargs):
        Gtk.AboutDialog.__init__(self, **kwargs)
        self.set_logo(GdkPixbuf.Pixbuf.new_from_resource('/org/readmachine/ocrd-browser/icons/logo.png'))
        self.set_version(__version__)


@Gtk.Template(filename=resource_filename(__name__, 'resources/open-dialog.ui'))
class OpenDialog(Gtk.FileChooserDialog):
    __gtype_name__ = "OpenDialog"

    def __init__(self, **kwargs):
        Gtk.FileChooserDialog.__init__(self, **kwargs)

        filter_text = Gtk.FileFilter()
        filter_text.set_name("METS files")
        filter_text.add_mime_type("text/xml")
        self.add_filter(filter_text)

        filter_any = Gtk.FileFilter()
        filter_any.set_name("Any files")
        filter_any.add_pattern("*")
        self.add_filter(filter_any)


@Gtk.Template(filename=resource_filename(__name__, 'resources/page-list.ui'))
class PagePreviewList(Gtk.IconView):
    __gtype_name__ = "PagePreviewList"

    def __init__(self, document: Document, **kwargs):
        super().__init__(**kwargs)
        self.document: Document = None
        self.current: Gtk.TreeIter = None
        self.model: LazyLoadingListStore = None
        self.loading_image_pixbuf: GdkPixbuf.Pixbuf = None
        self.file_lookup: dict = None
        self.setup_ui()
        self.set_document(document)

    def set_document(self, document):
        self.document = document
        self.setup_model()

    def setup_ui(self):
        theme = Gtk.IconTheme.get_default()
        self.loading_image_pixbuf = theme.load_icon_for_scale('image-loading', Gtk.IconSize.LARGE_TOOLBAR, 48, 0)
        self.set_text_column(0)
        self.set_tooltip_column(1)
        self.set_pixbuf_column(3)
        text_renderer: Gtk.CellRendererText = \
            [cell for cell in self.get_cells() if isinstance(cell, Gtk.CellRendererText)][0]
        text_renderer.props.ellipsize = Pango.EllipsizeMode.MIDDLE

    def setup_model(self):
        self.file_lookup = self.get_image_paths()
        self.model = LazyLoadingListStore(str, str, str, GdkPixbuf.Pixbuf,
                                          init_row=self.init_row, load_row=self.load_row, hash_row=self.hash_row)
        for page_id in self.document.page_ids:
            file = str(self.file_lookup[page_id])
            self.model.append((page_id, '', file, None))
        self.set_model(self.model)
        GLib.timeout_add(10, self.model.start_loading)

    def init_row(self, row: Gtk.TreeModelRow):
        row[1] = 'Loading {}'.format(row[2])
        row[3] = self.loading_image_pixbuf

    @staticmethod
    def load_row(row):
        image = cv2.imread(row[2])
        row[1] = '{} ({}x{})'.format(row[2], image.shape[1], image.shape[0])
        row[3] = cv_to_pixbuf(cv_scale(image, 100, None))
        return row

    @staticmethod
    def hash_row(row: Gtk.TreeModelRow):
        file = row[2]
        mtime = os.path.getmtime(file)
        return '{}:{}'.format(file, mtime)

    def get_image_paths(self, file_group='OCR-D-IMG'):
        images = self.document.workspace.mets.find_files(fileGrp=file_group)
        page_ids = self.document.workspace.mets.get_physical_pages(for_fileIds=[image.ID for image in images])
        file_paths = [self.document.path(image.url) for image in images]
        return dict(zip(page_ids, file_paths))

    def goto_index(self, index):
        index = index if index >= 0 else len(self.model) + index
        if 0 <= index < len(self.model):
            self.goto_path(Gtk.TreePath(index))

    def skip(self, pos):
        iterate = self.model.iter_previous if pos < 0 else self.model.iter_next
        n = iterate(self.current)
        self.goto_path(self.model.get_path(n))

    def goto_path(self, path):
        self.unselect_all()
        self.select_path(path)
        self.set_cursor(path, None, False)
        self.set_cursor(path, None, False)
        self.emit('activate_cursor_item')

    def do_item_activated(self, path: Gtk.TreePath):
        self.current = self.model.get_iter(path)
        # Trigger on_row_changed
        self.model[self.current][0] = self.model[self.current][0]
        self.emit('page_selected', self.model[path][0])

    @GObject.Signal()
    def page_selected(self, page_id: str):
        pass
