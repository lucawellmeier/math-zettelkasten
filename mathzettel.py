#!/usr/bin/env python

import os
import re
import time
import math
import threading
import argparse
import subprocess
import sqlite3
import markdown2
import chevron



zettelkasten_dir = '/home/luca/.local/math-zettelkasten'
archive_path = os.path.join(zettelkasten_dir, 'archive.db')
templates_path = os.path.join(zettelkasten_dir, 'templates')
html_path = os.path.join(zettelkasten_dir, 'html')






class Archive:
    def __init__(self, htmlgen):
        self.editor_running = False
        self.htmlgen = htmlgen
        self.db = sqlite3.connect(archive_path, check_same_thread=False)
        cur = self.db.cursor()
        cur.execute('''
                CREATE TABLE IF NOT EXISTS zettel (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shortcut TEXT,
                date INTEGER)
                ''')
        self.db.commit()

    def _find_id(self, key):
        cur = self.db.cursor()
        cur.execute('SELECT id FROM zettel WHERE zettel.id = ? OR zettel.shortcut = ?', 
            [key, key])
        return cur.fetchone()[0]

    def new(self):
        cur = self.db.cursor()
        cur.execute('INSERT INTO zettel (shortcut, date) VALUES ("", ?)', 
                [math.floor(time.time())])
        self.db.commit()
        id = cur.lastrowid

        filename = os.path.join(zettelkasten_dir, str(id) + '.md')
        open(filename, 'w').write('''---\nshortcut: \n---\n\n''')
        
        self.edit(id)
        
    def _file_watchdog(self, id):
        filename = os.path.join(zettelkasten_dir, str(id) + '.md')

        cur = self.db.cursor()

        initial_stat = os.stat(filename).st_mtime
        while self.editor_running:
            time.sleep(0.01)
            new_stat = os.stat(filename).st_mtime
            if initial_stat != new_stat:
                initial_stat = new_stat

                meta = MetaParser1(open(filename, 'r').readlines())
                cur.execute('UPDATE zettel SET shortcut = ?, date = ? WHERE id = ?', 
                        [meta.shortcut, math.floor(time.time()), id])
                self.db.commit()

                self._generate_zettel(id, meta.content)
                self._generate_index()

    def edit(self, key):
        id = self._find_id(key)
        
        watchdog = threading.Thread(target=self._file_watchdog, args=(id,))
        watchdog.start()
        self.editor_running = True
        
        filename = os.path.join(zettelkasten_dir, str(id) + '.md')
        subprocess.call(['nvim', filename])

        self.editor_running = False
        watchdog.join()
        
        meta = MetaParser1(open(filename, 'r').readlines())
        cur = self.db.cursor()
        cur.execute('UPDATE zettel SET shortcut = ?, date = ? WHERE id = ?', 
                [meta.shortcut, math.floor(time.time()), id])
        self.db.commit()
        
        self._generate_zettel(id, meta.content)
        self._generate_index()

    def list(self):
        cur = self.db.cursor()
        cur.execute('SELECT * FROM zettel ORDER BY date DESC')
        zettel = cur.fetchall()
        print('Found ' + str(len(zettel)) + ' Zettel.')
        for z in zettel:
            line = ''
            if z[1]:
                line += z[1]
            else:
                line += str(z[0])
            print(line)

    def _generate_index(self):
        cur = self.db.cursor()
        cur.execute('SELECT * FROM zettel ORDER BY date DESC')
        
        all_zettel = []
        for zettel in cur.fetchall():
            if zettel[1]:
                all_zettel.append({'shortcut': zettel[1]}) 
            else:
                all_zettel.append({'shortcut': zettel[0]})
        self.htmlgen.generate_index(all_zettel)

    def _generate_zettel(self, key, content):
        cur = self.db.cursor()
        cur.execute('SELECT * FROM zettel WHERE id = ? or shortcut = ?', [key, key])

        zettel = cur.fetchone()
        shortcut = zettel[1] if zettel[1] else str(zettel[0])
        self.htmlgen.generate_zettel(shortcut, content) 
             




class HTMLGenerator:
    def __init__(self):
        os.makedirs(templates_path, exist_ok=True)
        os.makedirs(html_path, exist_ok=True)
        self._assert_template_existence('base', 
                '''
                <html>
                <head>
                <meta charset="utf-8">
                <script>
                  MathJax = {
                    tex: {
                      inlineMath: [['$', '$']],
                      displayMath: [['$$', '$$']]
                    },
                    svg: {
                      fontCache: 'global'
                    }
                  };
                </script>
                <script src="https://polyfill.io/v3/polyfill.min.js?features=es6"></script>
                <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
                </head>
                <body>
                {{> main }}
                </body>
                </html>
                ''')
        self._assert_template_existence('index', 
                '''
                <h1> Zettelkasten </h1>
                <ul>
                {{# zettel }}
                  <li>
                    <a href="{{shortcut}}.html">{{shortcut}}</a>
                  </li>
                {{/ zettel }}
                </ul>
                ''')
        self._assert_template_existence('zettel', 
                '''
                <a href="index.html">Zettelkasten</a>
                <br>
                <code>{{shortcut}}</code>
                <article>
                  {{> content}}
                </article>
                ''')

    def _assert_template_existence(self, name, default_html):
        path = os.path.join(templates_path, name + '.html') 
        if not os.path.exists(path):
            open(path, 'w').write(default_html)

    def generate_index(self, all_zettel):
        index_path = os.path.join(templates_path, 'index.html')
        base_args = {
            'data': {'zettel': all_zettel},
            'partials_dict': {'main': open(index_path, 'r').read()},
            # not working for some reason
            # 'partials_path': templates_path,
            # 'partials_ext': '.html'
        }
        base_path = os.path.join(templates_path, 'base.html')
        html = chevron.render(open(base_path, 'r'), **base_args)
        
        outfile = os.path.join(html_path, 'index.html')
        open(outfile, 'w').write(html)

    def generate_zettel(self, key, content):
        zettel_path = os.path.join(templates_path, 'zettel.html')
        base_args = {
            'data': {'shortcut': key},
            'partials_dict': {
                'main': open(zettel_path, 'r').read(), 
                'content': markdown2.markdown(content),
            },
            # 'partials_path': templates_path,
            # 'partials_ext': '.html'
        }
        base_path = os.path.join(templates_path, 'base.html')
        html = chevron.render(open(base_path, 'r'), **base_args)
        
        outfile = os.path.join(html_path, key + '.html')
        open(outfile, 'w').write(html)




class MetaParser1:
    def __init__(self, lines):
        self.content, fields = self._parse_frontmatter(lines)
        self.shortcut = fields['shortcut']

    def _parse_frontmatter(self, lines):
        delims = []
        for i in range(len(lines)):
            line = lines[i]
            if line.strip() == '---':
                delims.append(i)

        frontmatter = lines[delims[0]+1:delims[1]]
        fields = {}
        for line in frontmatter:
            parts = line.split(':', 1)
            field = parts[0].strip()
            value = parts[1].strip()
            fields[field] = value

        return markdown2.markdown(''.join(lines[delims[1]+1:])), fields





parser = argparse.ArgumentParser(prog='mathzettel')
subparsers = parser.add_subparsers(dest='command')

new_group = subparsers.add_parser('new', prog='mathzettel new',
        help='create new Zettel')

edit_group = subparsers.add_parser('edit', prog='mathzettel edit',
        help='edit Zettel')
edit_group.add_argument('id',
        help='id or shortcut name of Zettel')

list_group = subparsers.add_parser('list', prog='mathzettel list', 
        help='list all inserted Zettel')

view_command = subparsers.add_parser('view', prog='mathzettel view', 
        help='open web browser for viewing the html')


htmlgen = HTMLGenerator()
archive = Archive(htmlgen)

options = parser.parse_args()
if options.command == 'new':
    archive.new()
elif options.command == 'edit':
    archive.edit(options.id)
elif options.command == 'list':
    archive.list()
elif options.command == 'view':
    index_path = os.path.join(html_path, 'index.html')
    subprocess.call(['detach', 'surf', 'file://' + index_path])
    
