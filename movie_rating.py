#!/usr/bin/pyth n -tt
# -*- coding: utf-8 -*-

# Import {{{
import os
import sys
import re
import html
import urllib
import urllib2
import codecs
import gdata.spreadsheet.service
from optparse import OptionParser
from multiprocessing.dummy import Pool, cpu_count, Lock
from imogeen import prepare_opener, get_parsed_url_response, get_file_path
from nomnom_filter import (
    get_auth_data,
    get_json_file,
    connect_to_service,
    retrieve_spreadsheet_id,
    get_writable_worksheet,
    get_writable_cells,
)
# }}}

LOCK    = Lock()
FILTERS = get_json_file('movie_rating.json')

def extract_tokens(dirname):
    closer_re  = re.compile('[\)\[\}].*$')
    opener_re  = re.compile('[\(\[\{]')
    version_re = re.compile(FILTERS['version'], flags=re.IGNORECASE)
    release_re = re.compile(FILTERS['release'])
    space_re   = re.compile('[\.\_]')

    movies_list = closer_re.sub('',  dirname)
    movies_list = opener_re.sub('',  movies_list)
    movies_list = version_re.sub('', movies_list)
    movies_list = release_re.sub('', movies_list)
    movies_list = space_re.sub(' ',  movies_list)

    return movies_list

def extract_info(movie_title):
    info = [movie_title] \
         + rottentomatoes_info(movie_title) \
         + imdb_info(movie_title)

    # Print progress.
    sys.stdout.write(".")
    sys.stdout.flush()

    return info

def normalize_rating(rating):
    float_re   = re.compile('.*\d+\.\d+.*')
    slash_re   = re.compile('.*\d+\/\d+.*')
    percent_re = re.compile('.*\d+\%')
    na_re      = re.compile('N\/A')

    normalized_rating = rating.strip()

    # Skip not available values.
    if na_re.match(normalized_rating):
        return ''

    if float_re.match(normalized_rating):
        rating_base = 10
        if slash_re.match(normalized_rating):
            normalized_rating, rating_base = normalized_rating.split('/')
            rating_base                    = int(rating_base)

        if rating_base == 5:
            normalized_rating = float(normalized_rating) * rating_base * 4
        elif rating_base == 10:
            normalized_rating = float(normalized_rating) * rating_base
    elif slash_re.match(normalized_rating):
        normalized_rating = normalized_rating.split('/')[0]
    elif percent_re.match(normalized_rating):
        normalized_rating = normalized_rating.replace('%', '')

    return str(int(normalized_rating))

def prepare_site_opener(site_url):
    opener = prepare_opener(site_url)

    # Initialize cookie.
    request    = urllib2.Request(site_url)
    opener.open(request)

    return opener

def prepare_imdb_opener():
    return prepare_site_opener('http://www.imdb.com')

def imdb_info(movie_title, opener=prepare_imdb_opener()):
    # http://www.imdb.com/find?q=
    site_url   = 'http://www.imdb.com'
    search_url = '%s/find' % site_url
    response   = get_parsed_url_response(
        search_url,
        data=urllib.urlencode({ 'q': movie_title }),
        opener=opener
    )

    info = None
    if response:
        class_re = re.compile('findResult')
        res_row  = response.first('tr', { 'class': class_re })
        if res_row:
            href_suffix = res_row.first('a')['href'] if res_row.first('a') else None
            if href_suffix:
                movie_url  = '%s/%s' % (site_url, href_suffix)
                movie_page = get_parsed_url_response(movie_url, opener=opener)
                if movie_page:
                    movie_overview = movie_page.find(
                        'td',
                        { 'id': 'overview-top' }
                    )

                    movie_details = movie_overview.find(
                        'div', 
                        { 'class': 'star-box-details' }
                    )

                    imdb_rating_value, metacritic_rating_value = '', ''
                    if movie_details:
                        imdb_rating = movie_details.find(
                            'span', 
                            { 'itemprop': 'ratingValue' }
                        )
                        if imdb_rating:
                            # imdb_rating_value = '%s/10' % imdb_rating.string
                            imdb_rating_value = normalize_rating(
                                imdb_rating.string
                            )

                        metacritic_re = re.compile('Metacritic.com')
                        metacritic_rating = movie_details.find(
                            'a',
                            { 'title': metacritic_re }
                        )
                        if metacritic_rating:
                            metacritic_rating_value = normalize_rating(
                                metacritic_rating.string
                            )

                    movie_infobar = movie_overview.find(
                        'div',
                        { 'class': 'infobar' }
                    )
                    movie_duration_value, movie_genre_value = '', ''
                    if movie_infobar:
                        movie_duration = movie_infobar.find(
                            'time',
                            { 'itemprop': 'duration' }
                        )
                        if movie_duration:
                            movie_duration_value \
                                = movie_duration.string.replace('min', '').strip()

                        movie_genres = movie_infobar.findAll(
                            'span',
                            { 'itemprop': 'genre' }
                        )
                        movie_genre_value = ', '.join([
                            genre.string for genre in movie_genres
                        ])

                    movie_description = movie_overview.find(
                        'p',
                        { 'itemprop': 'description' }
                    )
                    movie_description_value = ''
                    if movie_description:
                        movie_description_value = movie_description.text

                    info = [
                        imdb_rating_value, 
                        metacritic_rating_value,
                        movie_duration_value,
                        movie_genre_value,
                        movie_description_value,
                    ]

                    movie_page.decompose()

        response.decompose()

    return info if info else ['']*5

def prepare_rotten_opener():
    return prepare_site_opener('http://www.rottentomatoes.com/')

def rottentomatoes_info(movie_title, opener=prepare_rotten_opener()):
    # http://www.rottentomatoes.com/search/?search=
    site_url   = 'http://www.rottentomatoes.com'
    search_url = '%s/search/' % site_url
    response   = get_parsed_url_response(
        search_url,
        data=urllib.urlencode({ 'search': movie_title }),
        opener=opener
    )

    info = None
    if response:
        if response.find('ul', { 'id': 'movie_results_ul' }):
            movie_li = response.find('ul', { 'id': 'movie_results_ul' }).first('li')
            if movie_li:
                # Extract movie url from list.
                href_re    = re.compile('articleLink')
                movie_href = '%s%s' % (
                    site_url, 
                    movie_li.find('a', { 'class': href_re })['href']
                )

                # Fetch movie info.
                response = get_parsed_url_response(movie_href, opener=opener)
                info     = rottentomatoes_movie_info(response)
        elif response.find('h1', { 'class': 'movie_title' }):
            info = rottentomatoes_movie_info(response)

        response.decompose()

    return info if info else ['']*2

def rottentomatoes_movie_info(response):
    score_panel = response.find('div', { 'id': 'scorePanel' })

    # Tomatometer rating.
    tomato_meter       = score_panel.find('a', { 'id': 'tomato_meter_link' })
    tomato_meter_value = ''
    if tomato_meter:
        rating_value = tomato_meter.find('span', { 'itemprop': 'ratingValue' })
        if rating_value:
            # tomato_meter_value = '%s%%' % rating_value.string
            tomato_meter_value = normalize_rating(rating_value.string)

    # Audience score.
    audience_re          = re.compile('audience-score')
    audience_meter       = score_panel.find('div', { 'class': audience_re })
    audience_meter_value = ''
    if audience_meter:
        rating_value = audience_meter.find('span', { 'itemprop': 'ratingValue' })
        if rating_value:
            # audience_meter_value = '%s%%' % rating_value.string
            audience_meter_value = normalize_rating(rating_value.string)

    return [
        tomato_meter_value,
        audience_meter_value,
    ]

def write_movie_info(client, writable_cells, movie_info):
    # Prepare request that will be used to update worksheet cells.
    batch_request = gdata.spreadsheet.SpreadsheetsCellsFeed()

    cell_index = 0
    for movie in movie_info:
        for value in movie:
            # Fetch next cell.
            text_cell = writable_cells.entry[cell_index]

            # Update cell value.
            text_cell.cell.inputValue = value
            batch_request.AddUpdate(text_cell)

            # Go to next cell.
            cell_index += 1

    # Execute batch update of destination cells.
    return client.ExecuteBatch(
        batch_request, writable_cells.GetBatchLink().href
    )

def main():
    # Cmd options parser
    option_parser = OptionParser()

    option_parser.add_option("-d", "--dir")
    option_parser.add_option("-a", "--auth-data")

    (options, args) = option_parser.parse_args()

    if not (options.dir and options.auth_data):
        option_parser.print_help()
    else:
        dirs = os.listdir(options.dir)

        if dirs and FILTERS:
            # Create workers pool.
            workers_count = cpu_count()
            pool          = Pool(workers_count)

            print(u'Reading movies directory.')
            tokens = pool.map(extract_tokens, dirs)
            # tokens = tokens[0:20]
            print(u'Fetching %d movies info.' % len(tokens))
            info   = pool.map(extract_info, tokens)
            # End progress print.
            sys.stdout.write("\n")
            sys.stdout.flush()

            if info:
                # Append headers.
                headers = [
                    "Title",
                    "Tomato",
                    "Audience",
                    "IMDB",
                    "Metacritic",
                    "Length",
                    "Genre",
                    "Description",
                ]
                info.insert(0, headers)

                movies_len  = len(info)
                columns_len = len(headers)

                # Drive connecton boilerplate.
                print("Authenticating to Google service.")
                auth_data = get_auth_data(options.auth_data)
                client    = connect_to_service(auth_data)

                # Fetch spreadsheet id.
                spreadsheet_title = u'Karty'
                ssid              = retrieve_spreadsheet_id(client, spreadsheet_title)

                # Destination worksheet boilerplate.
                dst_name      = u'Filmoceny'
                print(u"Fetching destination worksheet '%s'." % dst_name)
                dst_worksheet = get_writable_worksheet(
                    client,
                    dst_name,
                    ssid,
                    row_count=movies_len,
                    col_count=columns_len,
                )

                print("Fetching destination cells.")
                writable_cells = get_writable_cells(
                    client,
                    dst_worksheet,
                    ssid,
                    max_row=movies_len,
                    max_col=columns_len,
                )

                print('Writing movies info.')
                write_movie_info(client, writable_cells, info)

if __name__ == "__main__":
    main()