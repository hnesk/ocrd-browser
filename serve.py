import os
import sys
import io
from functools import lru_cache
from pathlib import Path
from subprocess import Popen
from shutil import which
import html
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler
from socketserver import ForkingTCPServer
import urllib
import click

class RequestHandler(SimpleHTTPRequestHandler):
    bwhost = "localhost"
    bwport = 8085
    basedir = "."

    def do_GET(self):
        # FIXME: HTTP auth # self.server.auth / self.checkAuthentication()
        self.bwhost = self.headers.get('Host').split(':')[0]
        # serve a listing of available workspaces with links to ocrd-browse them
        if self.path == '/':
            self._serve_workspaces()
        # serve a single workspace
        elif self.path.startswith('/browse/'):
            path = self.path[7:].lstrip('/')
            path = urllib.parse.unquote(path)
            path = os.path.join(self.basedir, path)
            self._browse_workspace(path)
        elif self.path == '/reindex':
            self._workspaces.cache_clear()
            self.send_response(HTTPStatus.OK)
        else:
            #SimpleHTTPRequestHandler.do_GET(self)
            self.send_response(HTTPStatus.FORBIDDEN)

    def do_POST(self):
        self.do_GET()

    @property
    @lru_cache(maxsize=1)
    def _workspaces(self):
        # recursively find METS file paths
        paths = []
        for mets in Path(self.basedir).rglob('mets.xml'):
            if mets.match('.backup/*/mets.xml'):
                continue
            print(mets)
            paths.append(str(mets))
        return paths

    def _serve_workspaces(self):
        # generate HTML with links
        enc = sys.getfilesystemencoding()
        basedir = os.path.realpath(self.basedir)
        title = html.escape(basedir, quote=False)
        title = 'OCR-D Browser for workspaces at %s' % title
        r = []
        r.append('<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN" '
                 '"http://www.w3.org/TR/html4/strict.dtd">')
        r.append('<html>\n<head>')
        r.append('<meta http-equiv="Content-Type" '
                 'content="text/html; charset=%s">' % enc)
        r.append('<title>%s</title>\n</head>' % title)
        r.append('<body>\n<h1>%s</h1>' % title)
        r.append('<hr>\n<ul>')
        for name in self._workspaces:
            relname = os.path.relpath(name, basedir)
            linkname = os.path.join('/browse', relname)
            r.append('<li><a href="%s">%s</a></li>'
                     % (urllib.parse.quote(linkname, errors='surrogatepass'),
                        html.escape(relname, quote=False)))
        r.append('</ul>\n<hr>\n</body>\n</html>\n')
        # write to file
        encoded = '\n'.join(r).encode(enc, 'surrogateescape')
        f = io.BytesIO()
        f.write(encoded)
        f.seek(0)
        # send file
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-type", "text/html; charset=%s" % enc)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.copyfile(f, self.wfile)

    def _browse_workspace(self, path):
        if not os.path.exists(path):
            self.send_response(HTTPStatus.NOT_FOUND)
        else:
            if not path.endswith('mets.xml'):
                path = os.path.join(path, 'mets.xml')
            ## run app
            Popen([which('browse-ocrd'),
                   '--maximize',
                   '--fullscreen',
                   '--display', ':' + str(self.bwport - 8080),
                   path])
            ## proxy does not work, because the follow-up requests would need to be forwarded, too:
            # response = urllib.request.urlopen('http://' + self.bwhost + ':' + str(self.bwport))
            # self.send_response(response.status)
            # for name, value in response.getheaders():
            #     self.send_header(name.rstrip(':'), value)
            # self.end_headers()
            # self.copyfile(response, self.wfile)
            ## so let's use temporary redirect instead
            self.send_response(HTTPStatus.SEE_OTHER) # or TEMPORARY_REDIRECT?
            self.send_header('Location', 'http://' + self.bwhost + ':' + str(self.bwport))
            self.end_headers()

    # def log_message(self, format, *args):
    #     """ Override to prevent stdout on requests """
    #     pass

@click.command(context_settings={'help_option_names': ['-h', '--help']})
@click.option('-P', '--bwport', default=8085, type=int, help="TCP port of Broadwayd to delegate to")
@click.option('-p', '--port', default=80, type=int, help="TCP port to bind the web server to")
@click.option('-l', '--listen', default="", type=str, help="network address to bind the web server to")
@click.option('-d', '--basedir', default=".", type=click.Path(exists=True, file_okay=False))                    
def cli(bwport, port, listen, basedir):
    Handler = RequestHandler
    Handler.bwport = bwport
    Handler.basedir = basedir
    ForkingTCPServer.allow_reuse_address = True
    with ForkingTCPServer((listen, port), Handler) as httpd:
        httpd.serve_forever()

if __name__ == '__main__':
    cli()
