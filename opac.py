#!/usr/bin/python2 -tt
# -*- coding: utf-8 -*-

# Import {{{
import re
import sys
import json
import time
import codecs
import socket
import subprocess
from datetime import datetime
from optparse import OptionParser

import lib.libraries
from lib.common import get_file_path, get_json_file
from lib.gdocs import (
    get_service_client,
    write_rows_to_worksheet,
)
from lib.xls import make_xls
from lib.automata import (
    browser_start,
    browser_stop,
    browser_timeout,
)
# }}}

# Lovely constants.
WORKSHEET_HEADERS = (u'author', u'title', u'info')

def get_library_status(books_list, library):
    if not books_list:
        return

    # Get library instance.
    library_class = 'n{0}'.format(library)
    library       = getattr(lib.libraries, library_class)()

    # Set timeout for request.
    socket_timeout = 10.0
    socket.setdefaulttimeout(socket_timeout)

    # Will contain books info.
    library_status, browser = [], None
    for book in books_list:
        # Start browser if required.
        retry_start_browser = 2
        while not browser and retry_start_browser:
            try:
                browser = browser_start()
                browser_load_library(browser, library)
            except socket.timeout:
                print(u'Browser restart failed.')
            finally:
                retry_start_browser -= 1
                if retry_start_browser:
                    print(u'Retry starting browser')

        # Check if browser started succsessfully.
        if not browser: continue

        # Retry when fetching book info
        # (usually triggered by browser hang).
        book_info        = None
        retry_book_fetch = 2
        while not book_info and retry_book_fetch:
            # Search first by isbn, then by title.
            search_field = 'title' if retry_book_fetch % 2 else 'isbn'

            # Try fetching book info.
            try:
                library.pre_process(browser)

                # Fetch book info.
                book_info = library.get_book_info(
                    browser, book, search_field
                )

                library.post_process(browser)
            except socket.timeout:
                print(u'Querying book info timed out.')
                browser_timeout(browser)
                browser = None

            # Append book info if present.
            if book_info:
                print(u'Succsessfully queried book info.')
                break
            else:
                # retry_book_fetch?
                retry_book_fetch -= 1
                if retry_book_fetch:
                    print(u'Retry book fetching')
            # Sleep for short time to avoid too frequent requests.
            time.sleep(1.0)

        # Append book info.
        library_status.append({
            'author': book['author'],
            'title' : '"%s"' % book['title'],
            'info'  : book_info if book_info else "Brak",
        })

    browser_stop(browser)

    # Restore default timeout value.
    socket.setdefaulttimeout(None)

    return library_status

def browser_load_library(browser, library):
    print(u'Loading search form.')
    browser.get(library.url)
    if library.title: assert library.title in browser.title
    return

def get_worksheet_name(shelf_name):
    return '{0} {1}'.format(
        shelf_name.capitalize().replace('-', ' '),
        get_today_date(),
    )

def get_today_date(): return datetime.today().strftime("%Y-%m-%d")

def get_books_list(file_name):
    file_path = get_file_path(file_name)

    books_list = None
    with codecs.open(file_path, 'r', 'utf-8') as file_handle:
        books_list = json.load(file_handle)

    return books_list

def write_books_to_gdata(auth_data, shelf_name, library_status):
    # Fetch gdata client.
    print("Authenticating to Google service.")
    client = get_service_client(auth_data)

    # Fetch spreadsheet params.
    spreadsheet_title  = u'Karty'

    books_status = [
        [book[header] for header in WORKSHEET_HEADERS]
        for book in library_status
    ]

    print("Writing books.")
    write_rows_to_worksheet(
        client,
        spreadsheet_title,
        get_worksheet_name(shelf_name),
        books_status,
    )

def write_books_to_xls(shelf_name, library_status):
    return make_xls(
        shelf_name,
        get_today_date(),
        WORKSHEET_HEADERS,
        library_status
    )

def get_books_source_file(source):
    return source if re.match(r'^.*\.json$', source) else 'imogeen_%s.json' % (
        source
    )

def refresh_books_list(source):
    script_file = get_file_path('imogeen.py')
    return subprocess.call([
        sys.executable,
        '-tt',
        script_file,
        '-s',
        source,
        '-i',
        '10058'
    ])

def main():
    # Fetch library data.
    libraries_data = get_json_file('opac.json')

    # Cmd options parser
    option_parser = OptionParser()

    # Add options
    option_parser.add_option("-r", "--refresh", action="store_true")
    option_parser.add_option("-a", "--auth-data")

    # Add library option.
    library_choices = libraries_data.keys()
    option_parser.add_option(
        "-l",
        "--library",
        type='choice',
        choices=library_choices,
        help="Choose one of {0}".format("|".join(library_choices)),
    )

    (options, args) = option_parser.parse_args()

    # Check for library name.
    if not options.library:
        option_parser.print_help()
        exit(-1)

    # Get source file for library.
    library_data = libraries_data[options.library]
    books_source = library_data['source']

    if options.refresh:
        print(u'Updating list of books from source "%s".' % books_source)
        refresh_books_list(books_source)

    books_source_file = get_books_source_file(books_source)

    # Read in books list.
    print(u'Reading in books list.')
    books_list = get_books_list(books_source_file)

    # Fetch books library status.
    print(u'Fetching {0} books library status.'.format(len(books_list)))
    library_status = get_library_status(books_list, options.library)

    # Check results list.
    if not library_status:
        print(u'No library status found.')
        exit(-1)

    # Write books status.
    if options.auth_data:
        write_books_to_gdata(
            options.auth_data, books_source, library_status
        )
    else:
        write_books_to_xls(
            books_source, library_status
        )

if __name__ == "__main__":
    main()
