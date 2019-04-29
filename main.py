#!/usr/bin/python3
# IMPORTS
from bs4 import BeautifulSoup
from subprocess import Popen
from zipfile import ZipFile
import argparse
import configparser
import inspect
import os
import pdftotext
import re
import requests
import sqlite3
import sys
import tempfile


# GLOBAL VARIABLES
# API and HEADER settings according to this resource
# https://crosscite.org/docs.html
DOI_URL = "https://doi.org/"
DOI_HEADER = {'Accept': "application/x-bibtex"}
# arXiv url according to docs from here https://arxiv.org/help/oa
ARXIV_URL = "https://export.arxiv.org/oai2?verb=GetRecord&metadataPrefix=arXiv&identifier=oai:arXiv.org:"
# DOI regex used for matching DOIs
DOI_REGEX = r'(10\.[0-9a-zA-Z]+\/(?:(?!["&\'])\S)+)\b'
# custom database keys which are not part of the biblatex default keys
# this dict may also hold all those keys that require special parameters
TABLE_KEYS = {
    'label':    "primary key not null",
    'type':     "not null",
    'doi':      "",
    'eprint':   "",
    'file':     "",
    'tags':     "",
    'abstract': ""
    }
# list of CHECK constraints which are added to the database table definition
TABLE_CONSTRAINTS = [
    'doi is not null or eprint is not null',
    '(type = "article" and author not null and title not null and journal not null and year not null) or \
    (type = "book" and author not null and title not null and year not null) or \
    (type = "collection" and editor not null and title not null and year not null) or \
    (type = "proceedings" and title not null and year not null) or \
    (type = "report" and author not null and title not null and institution not null and year not null) or \
    (type = "thesis" and author not null and title not null and institution not null and year not null) or \
    (type = "unpublished" and author not null and title not null and year not null)',
    ]
# biblatex default types and required values taken from their docs
# https://ctan.org/pkg/biblatex
BIBTEX_TYPES = {
    'article': ['author', 'title', 'journal', 'year'],
    'book': ['author', 'title', 'year'],
    'collection': ['editor', 'title', 'year'],
    'proceedings': ['title', 'year'],
    'report': ['author', 'title', 'type', 'institution', 'year'],
    'thesis': ['author', 'title', 'type', 'institution', 'year'],
    'unpublished': ['author', 'title', 'year']
    }
# global config
# the default configuration file will be loaded from ~/.config/crema/config.ini
CONFIG = configparser.ConfigParser()


# ARGUMENT FUNCTIONS
def init_(args):
    """
    Initializes the sqlite3 database at the configured location.
    A single table is used which is named in the config file.
    The initial columns correspond to all minimally required values of the
    default biblatex types plus the custom keys defined initially.
    All fields are TEXT fields and do not have any special attributes. If an
    entry must not be NULL it should be declared in the TABLE_KEYS dictionary
    with its according parameters.
    """
    conf_database = dict(CONFIG['DATABASE'])
    path = os.path.expanduser(conf_database['path'])
    conn = sqlite3.connect(path)
    cmd = "CREATE TABLE "+conf_database['table']+"(\n"
    for type, keys in BIBTEX_TYPES.items():
        for key in keys:
            if key not in TABLE_KEYS.keys():
                TABLE_KEYS[key] = ""
    for key, params in TABLE_KEYS.items():
        cmd += key+' text '+params+',\n'
    for constraint in TABLE_CONSTRAINTS:
        cmd += "CHECK ("+constraint+"),\n"
    cmd = cmd[:-2]+'\n)'
    try:
        conn.execute(cmd)
        conn.commit()
    except sqlite3.Error as e:
        print(e)
    finally:
        conn.close()


def list_(args):
    """
    By default, all entries of the database are listed.
    This output can be filtered by providing values for any set of table keys.
    """
    if '--' in args:
        args.remove('--')
    parser = argparse.ArgumentParser(prog="list", description="List subcommand parser.",
                                     prefix_chars='+-')
    parser.add_argument('-x', '--or', dest='OR', action='store_true',
                        help="concatenate filters with OR instead of AND")
    conf_database = dict(CONFIG['DATABASE'])
    path = os.path.expanduser(conf_database['path'])
    conn = sqlite3.connect(path)
    try:
        cursor = conn.execute("PRAGMA table_info("+conf_database['table']+")")
    except sqlite3.Error as e:
        print(e)
    for row in cursor:
        parser.add_argument('++'+row[1], type=str, action='append',
                            help="include elements with matching "+row[1])
        parser.add_argument('--'+row[1], type=str, action='append',
                            help="exclude elements with matching "+row[1])
    largs = parser.parse_args(args)
    filter = ''
    for f in largs._get_kwargs():
        if f[0] == 'OR' or f[1] is None:
            continue
        if not isinstance(f[1], list):
            f[1] = [f[1]]
        for i in f[1]:
            if filter == '':
                filter = 'WHERE '
            else:
                if largs.OR:
                    filter += ' OR '
                else:
                    filter += ' AND '
            filter += f[0]
            for index, object in enumerate(sys.argv):
                if i in object:
                    if sys.argv[index-1][0] == '-':
                        filter += ' NOT'
                    break
            filter += ' LIKE "%' + i + '%"'
    cmd = "SELECT rowid, label, title, tags FROM "+conf_database['table']+' '+filter
    ids = []
    try:
        cursor = conn.execute(cmd)
        for row in cursor:
            ids.append(row[0])
            print(row)
    except sqlite3.Error as e:
        print(e)
    finally:
        conn.close()
    return ids


def show_(args):
    """
    Prints the details of a selected entry in bibtex format to stdout.
    """
    parser = argparse.ArgumentParser(prog="show", description="Show subcommand parser.")
    parser.add_argument("id", type=int, help="row ID of the entry")
    if (len(args) == 0):
        parser.print_usage(sys.stderr)
        sys.exit(1)
    largs = parser.parse_args(args)
    conf_database = dict(CONFIG['DATABASE'])
    path = os.path.expanduser(conf_database['path'])
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cmd = "SELECT * FROM "+conf_database['table']+" WHERE rowid = "+str(largs.id)
    try:
        cursor = conn.execute(cmd)
        for row in cursor:
            print(_dict_to_bibtex(dict(row)))
    except sqlite3.Error as e:
        print(e)
    finally:
        conn.close()


def open_(args):
    """
    Opens the associated file of an entry with xdg-open.
    """
    parser = argparse.ArgumentParser(prog="open", description="Open subcommand parser.")
    parser.add_argument("id", type=int, help="row ID of the entry")
    if (len(args) == 0):
        parser.print_usage(sys.stderr)
        sys.exit(1)
    largs = parser.parse_args(args)
    conf_database = dict(CONFIG['DATABASE'])
    path = os.path.expanduser(conf_database['path'])
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cmd = "SELECT * FROM "+conf_database['table']+" WHERE rowid = "+str(largs.id)
    try:
        cursor = conn.execute(cmd)
        for row in cursor:
            entry = dict(row)
            if entry['file'] is None:
                print("Error: There is no file associated with this entry.")
                sys.exit(1)
            Popen(["xdg-open", entry['file']], stdin=None, stdout=None, stderr=None, close_fds=True, shell=False)
    except sqlite3.Error as e:
        print(e)
    finally:
        conn.close()


def add_(args):
    """
    Adds new entries to the database.
    """
    parser = argparse.ArgumentParser(prog="add", description="Add subcommand parser.")
    parser.add_argument("-l", "--label", type=str,
                        help="the label for the new database entry")
    group_add = parser.add_mutually_exclusive_group()
    group_add.add_argument("-a", "--arxiv", type=str,
                           help="arXiv ID of the new references")
    group_add.add_argument("-d", "--doi", type=str,
                           help="DOI of the new references")
    group_add.add_argument("-p", "--pdf", type=argparse.FileType('rb'),
                           help="PDFs files to be added")
    parser.add_argument("tags", nargs=argparse.REMAINDER)
    if (len(args) == 0):
        parser.print_usage(sys.stderr)
        sys.exit(1)
    largs = parser.parse_args(args)

    dois = {}
    def flatten(l): return [item for sublist in l for item in sublist]
    if largs.arxiv is not None:
        page = requests.get(ARXIV_URL+largs.arxiv)
        xml = BeautifulSoup(page.text, features='xml')
        entry = _parse_arxiv(xml)
        if largs.label is not None:
            entry['label'] = largs.label
        if 'doi' in entry.keys():
            dois[entry['doi']] = entry
        else:
            if largs.tags is not None:
                entry['tags'] = ''.join(tag.strip('+')+' ' for tag in largs.tags).strip()
            _insert_entry(entry)
    if largs.pdf is not None:
        def most_common(lst: list): return max(set(matches), key=matches.count)
        pdf_obj = pdftotext.PDF(largs.pdf)
        text = "".join(pdf_obj)
        matches = re.findall(DOI_REGEX, text)
        dois[most_common(matches)] = {'file': largs.pdf.name}
    if largs.doi is not None:
        dois[largs.doi] = {}
    for doi, extra in dois.items():
        assert(re.match(DOI_REGEX, doi))
        page = requests.get(DOI_URL+doi, headers=DOI_HEADER)
        entry = _bibtex_to_dict(page.text)
        if largs.label is not None:
            entry['label'] = largs.label
        if largs.tags is not None:
            entry['tags'] = ''.join(tag.strip('+')+' ' for tag in largs.tags).strip()
        _insert_entry({**entry, **extra})


def edit_(args):
    """
    Opens an existing entry for manual editing.
    """
    parser = argparse.ArgumentParser(prog="edit", description="Edit subcommand parser.")
    parser.add_argument("id", type=int, help="row ID of the entry")
    if (len(args) == 0):
        parser.print_usage(sys.stderr)
        sys.exit(1)
    largs = parser.parse_args(args)
    id = largs.id
    conf_database = dict(CONFIG['DATABASE'])
    path = os.path.expanduser(conf_database['path'])
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cmd = "SELECT * FROM "+conf_database['table']+" WHERE rowid = "+str(id)
    prev = ''
    try:
        cursor = conn.execute(cmd)
        for row in cursor:
            prev += _dict_to_bibtex(dict(row))+'\n'
    except sqlite3.Error as e:
        print(e)
    tmp_file = tempfile.NamedTemporaryFile(mode='w+')
    tmp_file.write(prev)
    tmp_file.flush()
    status = os.system(os.environ['EDITOR'] + ' ' + tmp_file.name)
    assert status == 0
    tmp_file.seek(0, 0)
    next = tmp_file.read()
    tmp_file.close()
    assert not os.path.exists(tmp_file.name)
    if prev == next:
        conn.close()
        return
    entry = _bibtex_to_dict(next)
    update = "UPDATE "+conf_database['table']+" SET "
    for k, v in entry.items():
        update += k + " = '" + v + "', "
    update = update[:-2] + " WHERE rowid = "+str(id)
    try:
        cursor = conn.execute(update)
        conn.commit()
    except sqlite3.Error as e:
        print(e)
    finally:
        conn.close()


def export_(args):
    """
    Exports all entries matched by the filter queries (see the list docs).
    Currently supported exporting formats are:
    * bibtex databases
    * zip archives
    """
    parser = argparse.ArgumentParser(prog="export", description="Export subcommand parser.")
    parser.add_argument("-b", "--bibtex", type=argparse.FileType('a'),
                        help="BibTeX output file")
    parser.add_argument("-z", "--zip", type=argparse.FileType('a'),
                        help="zip output file")
    parser.add_argument('list_args', nargs=argparse.REMAINDER)
    if (len(args) == 0):
        parser.print_usage(sys.stderr)
        sys.exit(1)
    largs = parser.parse_args(args)
    if largs.bibtex is None and largs.zip is None:
        return
    if largs.zip is not None:
        largs.zip = ZipFile(largs.zip.name, 'w')
    ids = list_(largs.list_args)
    conf_database = dict(CONFIG['DATABASE'])
    path = os.path.expanduser(conf_database['path'])
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cmd = "SELECT * FROM "+conf_database['table']+" WHERE rowid IN ("+', '.join([str(id) for id in ids])+')'
    try:
        cursor = conn.execute(cmd)
        for row in cursor:
            if largs.bibtex is not None:
                largs.bibtex.write(_dict_to_bibtex(dict(row))+'\n')
            if largs.zip is not None:
                file = dict(row)['file']
                if file is not None:
                    largs.zip.write(file, dict(row)['label']+'.pdf')
    except sqlite3.Error as e:
        print(e)
    finally:
        conn.close()


# HELPER FUNCTIONS
def _insert_entry(entry: dict):
    """
    Inserts an entry into the database.
    This function has the following side effects:
    * any missing key columns are inserted into the database
    * if a duplicate entry appears to exist, nothing happens
    """
    # load database info
    conf_database = dict(CONFIG['DATABASE'])
    conn = sqlite3.connect(conf_database['path'])
    try:
        cursor = conn.execute("PRAGMA table_info("+conf_database['table']+")")
    except sqlite3.Error as e:
        print(e)
    table_keys = [row[1] for row in cursor]

    # extract information from bibtex
    keys = ''
    values = ''
    for key, value in entry.items():
        if key not in table_keys:
            try:
                conn.execute("ALTER TABLE "+conf_database['table']+" ADD COLUMN "+key+" text")
                cursor = conn.execute("PRAGMA table_info("+conf_database['table']+")")
            except sqlite3.Error as e:
                print(e)
            table_keys = [row[1] for row in cursor]
        keys = "{},{}".format(keys, key)
        values = "{},'{}'".format(values, value)

    keys = keys.strip(',')
    values = values.strip(',')

    # insert into table
    cmd = "INSERT INTO "+conf_database['table']+" ("+keys+") VALUES ("+values+")"
    try:
        cursor.execute(cmd)
        conn.commit()
    except sqlite3.IntegrityError as e:
        print(e)
        print("Error: You already appear to have an identical entry in your database.")
    finally:
        conn.close()


def _parse_arxiv(xml):
    """
    Extracts an information dictionary from an arXiv XML export.
    """
    entry = {}
    entry['archivePrefix'] = 'arXiv'
    for key in xml.metadata.arXiv.findChildren(recursive=False):
        if key.name == 'doi':
            entry['doi'] = key.contents[0]
        elif key.name == 'id':
            entry['eprint'] = key.contents[0]
        elif key.name == 'categories':
            entry['primaryClass'] = key.contents[0].split(' ')[0]
        elif key.name == 'created':
            entry['year'] = key.contents[0].split('-')[0]
            if 'label' in entry.keys():
                entry['label'] = entry['label'] + entry['year']
            else:
                entry['label'] = entry['year']
        elif key.name == 'title':
            entry['title'] = re.sub(r'\s+', ' ', key.contents[0].strip().replace('\n', ' '))
        elif key.name == 'authors':
            entry['author'] = ''
            first = True
            for author in key.findChildren(recursive=False):
                if first:
                    if 'label' in entry.keys():
                        entry['label'] = author.keyname.contents[0] + entry['label']
                    else:
                        entry['label'] = author.keyname.contents[0]
                    first = False
                entry['author'] += author.forenames.contents[0] + ' ' + author.keyname.contents[0] + ' and '
            entry['author'] = entry['author'][:-5]
        elif key.name == 'abstract':
            entry['abstract'] = re.sub(r'\s+', ' ', key.contents[0].strip().replace('\n', ' '))
        else:
            print("The key '{}' of this arXiv entry is not being processed!".format(key.name))
    if 'doi' in entry.keys():
        entry['type'] = 'article'
    else:
        entry['type'] = 'unpublished'
    return entry


def _bibtex_to_dict(bibtex: str):
    """
    Converts a bibtex formatted string into a dictionary of key-value pairs.
    """
    entry = {}
    lines = bibtex.split('\n')
    entry['type'] = re.findall(r'^@([a-zA-Z]*){', lines[0])[0]
    entry['label'] = re.findall(r'{(\w*),$', lines[0])[0]
    for line in lines[1:]:
        if line == '}':
            break
        key, value = line.split('=')
        entry[key.strip()] = re.sub(r'\s+', ' ', value.strip(' ,{}'))
    return entry


def _dict_to_bibtex(entry: dict):
    """
    Converts a key-value paired dictionary into a bibtex formatted string.
    """
    bibtex = "@"+entry['type']+"{"+entry['label']+","
    for key in sorted(entry):
        if entry[key] is not None and key not in ['type', 'label']:
            bibtex += "\n\t"+key+" = {"+str(entry[key])+"},"
    bibtex = bibtex.strip(',')+"\n}"
    return bibtex


# MAIN
def main():
    subcommands = []
    for key, value in globals().items():
        if inspect.isfunction(value) and 'args' in inspect.signature(value).parameters:
            subcommands.append(value.__name__[:-1])
    parser = argparse.ArgumentParser(description="Process input arguments.")
    parser.add_argument("-c", "--config", type=argparse.FileType('r'),
                        help="Alternative config file")
    parser.add_argument('command', help="subcommand to be called",
                        choices=subcommands)
    parser.add_argument('args', nargs=argparse.REMAINDER)

    if (len(sys.argv) == 1):
        parser.print_usage(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    if args.config is not None:
        CONFIG.read(args.config.name)
    else:
        CONFIG.read(os.path.expanduser('~/.config/crema/config.ini'))

    globals()[args.command+'_'](args.args)


if __name__ == '__main__':
    main()
