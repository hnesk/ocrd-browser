"""
Fixes warnings about unspecified version contraints a la:
PyGIWarning: GtkSource was imported without specifying a version first. Use gi.require_version('GtkSource', '4') before import to ensure that the right version gets loaded.

import with:

  import tests

in your Gtk using test file in the first line
"""
# pylint: disable=unused-import
from unittest import TestCase
import gi
from pathlib import Path
from ocrd_utils import initLogging

gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
try:
    gi.require_version('GtkSource', '4')
except ValueError:
    gi.require_version('GtkSource', '3.0')

initLogging()

TEST_BASE_PATH = (Path(__file__).parent).absolute()
ASSETS_PATH = (TEST_BASE_PATH / 'assets').absolute()
if not ASSETS_PATH.exists():
    raise RuntimeError('Assset path {} not found, please run: make tests/assets first')

# @see http://melp.nl/2011/02/phpunit-style-dataprovider-in-python-unit-test/
def data_provider(fn_data_provider):
    """Data provider decorator, allows another callable to provide the data for the test"""
    def test_decorator(fn):
        def repl(self, *args):
            for i in fn_data_provider():
                try:
                    fn(self, *i)
                except AssertionError:
                    print("Assertion error caught with data set ", i)
                    raise
        return repl
    return test_decorator


