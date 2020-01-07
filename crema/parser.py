"""CReMa parsing module"""

# IMPORTS
# standard
from collections import OrderedDict
import os
import re
import requests
# third-party
from bs4 import BeautifulSoup
from ruamel.yaml import YAML
from ruamel.yaml.compat import StringIO
import pdftotext
import bibtexparser

# GLOBAL VARIABLES
# API and HEADER settings according to this resource
# https://crosscite.org/docs.html
DOI_URL = "https://doi.org/"
DOI_HEADER = {'Accept': "application/x-bibtex"}
# arXiv url according to docs from here https://arxiv.org/help/oa
ARXIV_URL = "https://export.arxiv.org/api/query?id_list="
# DOI regex used for matching DOIs
DOI_REGEX = r'(10\.[0-9a-zA-Z]+\/(?:(?!["&\'])\S)+)\b'
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


class Entry():
    """Bibliography entry class"""
    class YamlDumper(YAML):
        """Wrapper class for dumping YAML"""
        # pylint: disable=arguments-differ,inconsistent-return-statements
        def dump(self, data, stream=None, **kw):
            inefficient = False
            if stream is None:
                inefficient = True
                stream = StringIO()
            YAML.dump(self, data, stream, **kw)
            if inefficient:
                return stream.getvalue()

    def __init__(self, label, data):
        self.label = label
        self.data = data.copy()

    def __repr__(self):
        return self.to_bibtex()

    def set_label(self, label):
        """Sets the label"""
        self.label = label
        self.data['ID'] = label

    def set_tags(self, tags):
        """Sets the tags"""
        self.data['tags'] = ''.join(tag.strip('+')+', ' for tag in tags).strip(', ')

    def set_file(self, file):
        """Sets the file"""
        self.data['file'] = os.path.abspath(file)

    def matches(self, _filter, _or):
        """Check whether the filter is matched"""
        match_list = []
        for key, values in _filter.items():
            if key[0] not in self.data.keys():
                match_list.append(not key[1])
            for val in values:
                if val not in self.data[key[0]]:
                    match_list.append(not key[1])
                else:
                    match_list.append(key[1])
        if _or:
            return any(m for m in match_list)
        return all(m for m in match_list)

    def to_bibtex(self):
        """Returns the Entry in bibtex format"""
        database = bibtexparser.bibdatabase.BibDatabase()
        database.entries = [self.data]
        return bibtexparser.dumps(database)

    def to_yaml(self):
        """Returns the Entry in YAML format"""
        yaml = Entry.YamlDumper()
        yaml.explicit_start = True
        yaml.explicit_end = True
        return yaml.dump({self.label: self.data})

    @staticmethod
    def from_bibtex(file, string=False):
        """Creates a new bibliography (dict of Entry instances) from a bibtex source file"""
        if string:
            database = bibtexparser.loads(file)
        else:
            database = bibtexparser.load(file)
        bib = OrderedDict()
        for entry in database.entries:
            bib[entry['ID']] = Entry(entry['ID'], entry)
        return bib

    @staticmethod
    def from_yaml(file):
        """Creates a new bibliography (dict of Entry instances) from a YAML source file"""
        yaml = YAML()
        bib = OrderedDict()
        for entry in yaml.load_all(file):
            for label, data in entry.items():
                bib[label] = Entry(label, data)
        return bib

    @staticmethod
    def from_doi(doi):
        """Queries the bibtex source from a given DOI"""
        assert re.match(DOI_REGEX, doi)
        page = requests.get(DOI_URL+doi, headers=DOI_HEADER)
        return Entry.from_bibtex(page.text, string=True)

    @staticmethod
    def from_arxiv(arxiv):
        # pylint: disable=too-many-branches
        """Queries the bibtex source from a given arxiv ID"""
        page = requests.get(ARXIV_URL+arxiv)
        xml = BeautifulSoup(page.text, features='html.parser')
        # TODO rewrite this to use a defaultdict(str)
        entry = {}
        entry['archivePrefix'] = 'arXiv'
        for key in xml.feed.entry.findChildren(recursive=False):
            # TODO key.name == 'category'
            # TODO key.name == 'link'
            # TODO key.name == 'updated'
            if key.name == 'arxiv:doi':
                entry['doi'] = str(key.contents[0])
            elif key.name == 'id':
                entry['arxivid'] = str(key.contents[0]).replace('http://arxiv.org/abs/', '')
                entry['eprint'] = str(key.contents[0])
            elif key.name == 'primary_category':
                entry['primaryClass'] = str(key.attrs['term'])
            elif key.name == 'published':
                entry['year'] = key.contents[0].split('-')[0]
                if 'ID' in entry.keys():
                    entry['ID'] = entry['ID'] + entry['year']
                else:
                    entry['ID'] = entry['year']
            elif key.name == 'title':
                entry['title'] = re.sub(r'\s+', ' ', key.contents[0].strip().replace('\n', ' '))
            elif key.name == 'author':
                if 'author' not in entry.keys():
                    first = True
                    entry['author'] = ''
                name = [n.contents[0] for n in key.findChildren()][0]
                if first:
                    if 'ID' in entry.keys():
                        entry['ID'] = name.split()[-1] + entry['ID']
                    else:
                        entry['ID'] = name.split()[-1]
                    first = False
                entry['author'] += '{} and '.format(name)
            elif key.name == 'summary':
                entry['abstract'] = re.sub(r'\s+', ' ', key.contents[0].strip().replace('\n', ' '))
            else:
                print("The key '{}' of this arXiv entry is not being processed!".format(key.name))
        if 'doi' in entry.keys():
            entry['ENTRYTYPE'] = 'article'
        else:
            entry['ENTRYTYPE'] = 'unpublished'
        # strip last 'and' from author field
        entry['author'] = entry['author'][:-5]
        bib = OrderedDict()
        bib[entry['ID']] = Entry(entry['ID'], entry)
        return bib

    @staticmethod
    def from_pdf(pdf):
        """Extracts the most common DOI from a pdf file"""
        def most_common(lst: list):
            return max(set(lst), key=lst.count)
        pdf_obj = pdftotext.PDF(pdf)  # pylint: disable=c-extension-no-member
        text = "".join(pdf_obj)
        matches = re.findall(DOI_REGEX, text)
        bib = Entry.from_doi(most_common(matches))
        for value in bib.values():
            value.set_file(pdf.name)
        return bib
