# -*- coding: utf-8 -*-

import sys
reload(sys)
sys.setdefaultencoding("utf-8")
import os

# Make hascore importable by adding the parent dir to the path
sys.path.append(os.path.dirname(os.getcwd()))

from collections import namedtuple
from urlparse import urljoin
import zipfile
import unicodecsv
import requests
from decimal import Decimal
from datetime import datetime
from progressbar import ProgressBar
import progressbar.widgets
from coaster.utils import getbool

from hascore import init_for
from hascore.models import db, GeoName, GeoCountryInfo, GeoAltName, GeoAdmin1Code, GeoAdmin2Code


unicodecsv.field_size_limit(sys.maxint)


CountryInfoRecord = namedtuple('CountryInfoRecord', ['iso_alpha2', 'iso_alpha3', 'iso_numeric',
    'fips_code', 'title', 'capital', 'area_in_sqkm', 'population', 'continent', 'tld',
    'currency_code', 'currency_name', 'phone', 'postal_code_format', 'postal_code_regex',
    'languages', 'geonameid', 'neighbours', 'equivalent_fips_code'])


GeoNameRecord = namedtuple('GeoNameRecord', ['geonameid', 'title', 'ascii_title', 'alternatenames',
    'latitude', 'longitude', 'fclass', 'fcode', 'country_id', 'cc2', 'admin1', 'admin2',
    'admin3', 'admin4', 'population', 'elevation', 'dem', 'timezone', 'moddate'])


GeoAdminRecord = namedtuple('GeoAdminRecord', ['code', 'title', 'ascii_title', 'geonameid'])

GeoAltNameRecord = namedtuple('GeoAltNameRecord', ['id', 'geonameid', 'lang', 'title',
    'is_preferred_name', 'is_short_name', 'is_colloquial', 'is_historic'])


def get_progressbar():
    return ProgressBar(
        widgets=[progressbar.widgets.Percentage(), ' ', progressbar.widgets.Bar(), ' ', progressbar.widgets.ETA(), ' '])


def downloadfile(basepath, filename):
    print "Downloading %s..." % filename
    url = urljoin(basepath, filename)
    r = requests.get(url, stream=True)
    if r.status_code == 200:
        progress = ProgressBar(maxval=int(r.headers.get('content-length', 0)),
            widgets=[progressbar.widgets.Percentage(), ' ',
                progressbar.widgets.Bar(), ' ',
                progressbar.widgets.ETA(), ' ']).start()
        bytes = 0
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(1024):
                if not chunk:
                    break  # Break when done. The connection remains open for Keep-Alive
                bytes += len(chunk)
                f.write(chunk)
                progress.update(bytes)
        progress.finish()

        if filename.lower().endswith('.zip'):
            zip = zipfile.ZipFile(filename, 'r')
            zip.extractall()


def load_country_info(fd):
    print "Loading country info..."
    progress = get_progressbar()
    countryinfo = [CountryInfoRecord(*row) for row in unicodecsv.reader(fd, delimiter='\t')
        if not row[0].startswith('#')]

    GeoCountryInfo.query.all()  # Load everything into session cache
    for item in progress(countryinfo):
        if item.geonameid:
            ci = GeoCountryInfo.query.get(int(item.geonameid))
            if ci is None:
                ci = GeoCountryInfo()
                db.session.add(ci)

            ci.iso_alpha2 = item.iso_alpha2
            ci.iso_alpha3 = item.iso_alpha3
            ci.iso_numeric = int(item.iso_numeric)
            ci.fips_code = item.fips_code
            ci.title = item.title
            ci.capital = item.capital
            ci.area_in_sqkm = Decimal(item.area_in_sqkm) if item.area_in_sqkm else None
            ci.population = int(item.population)
            ci.continent = item.continent
            ci.tld = item.tld
            ci.currency_code = item.currency_code
            ci.currency_name = item.currency_name
            ci.phone = item.phone
            ci.postal_code_format = item.postal_code_format
            ci.postal_code_regex = item.postal_code_regex
            ci.languages = item.languages.split(',')
            ci.geonameid = int(item.geonameid)
            ci.neighbours = item.neighbours.split(',')
            ci.equivalent_fips_code = item.equivalent_fips_code

            ci.make_name()

    db.session.commit()


def load_geonames(fd):
    progress = get_progressbar()
    print "Loading geonames..."
    size = sum(1 for line in fd)
    fd.seek(0)  # Return to start
    loadprogress = ProgressBar(maxval=size,
        widgets=[progressbar.widgets.Percentage(), ' ', progressbar.widgets.Bar(), ' ', progressbar.widgets.ETA(), ' ']).start()

    geonames = []

    # Feature descriptions: http://download.geonames.org/export/dump/featureCodes_en.txt
    # Sorting order, larger number has more weight
    loadfeatures = {
        ('L', 'CONT'):  21,  # Continent
        ('A', 'PCL'):   20,  # Political entity (country)
        ('A', 'PCLD'):  19,  # Dependent political entity
        ('A', 'PCLF'):  18,  # Freely associated state
        ('A', 'PCLI'):  17,  # Independent political entity
        ('A', 'PCLS'):  16,  # Semi-independent political entity
        ('A', 'ADM1'):  15,  # First-order administrative division (state, province)
        ('P', 'PPLC'):  14,  # capital of a political entity
        ('P', 'PPLA'):  13,  # Seat of a first-order administrative division (state capital)
        ('P', 'PPLA2'): 12,  # Seat of a second-order administrative division
        ('P', 'PPLA3'): 11,  # Seat of a third-order administrative division
        ('P', 'PPLA4'): 10,  # Seat of a fourth-order administrative division
        ('P', 'PPLG'):   9,  # Seat of government of a political entity
        ('P', 'PPL'):    8,  # Populated place (city, could be a neighbourhood too)
        ('P', 'PPLR'):   7,  # Religious populated place
        ('P', 'PPLS'):   6,  # Populated places
        ('P', 'PPLX'):   5,  # Section of populated place
        ('P', 'PPLL'):   4,  # Populated locality
        ('P', 'PPLF'):   3,  # Farm village
        ('A', 'ADM2'):   2,  # Second-order administrative division (district, county)
        ('A', 'ADM3'):   1,  # Third-order administrative division
        }

    for counter, line in enumerate(fd):
        loadprogress.update(counter)

        if not line.startswith('#'):
            rec = GeoNameRecord(*line.strip().split('\t'))
            # Ignore places that have a population below 15,000, but keep places that have a population of 0,
            # since that indicates data wasn't available
            if rec.fclass == 'P' and (
                    (rec.population.isdigit() and int(rec.population != 0) and int(rec.population) < 15000)
                    or not rec.population.isdigit()):
                continue
            if (rec.fclass, rec.fcode) not in loadfeatures:
                continue
            geonames.append(rec)

    loadprogress.finish()

    print "Sorting %d records..." % len(geonames)

    geonames = [row[2] for row in sorted(
        [(loadfeatures[(rec.fclass, rec.fcode)], int(rec.population) if rec.population else 0, rec) for rec in geonames],
        reverse=True)]
    GeoName.query.all()  # Load all data into session cache for faster lookup

    print "Processing %d records..." % len(geonames)

    for item in progress(geonames):
        if item.geonameid:
            gn = GeoName.query.get(int(item.geonameid))
            if gn is None:
                gn = GeoName()
                db.session.add(gn)

            gn.geonameid = int(item.geonameid)
            gn.title = item.title or None
            gn.ascii_title = item.ascii_title or None
            # gn.alternate_titles = item.alternatenames.split(',') if item.alternatenames else None
            gn.latitude = Decimal(item.latitude) or None
            gn.longitude = Decimal(item.longitude) or None
            gn.fclass = item.fclass or None
            gn.fcode = item.fcode or None
            gn.country_id = item.country_id or None
            gn.cc2 = item.cc2 or None
            gn.admin1 = item.admin1 or None
            gn.admin2 = item.admin2 or None
            gn.admin3 = item.admin3 or None
            gn.admin4 = item.admin4 or None
            gn.admin1code = gn.admin1_ref
            gn.admin2code = gn.admin2_ref
            gn.population = int(item.population) if item.population else None
            gn.elevation = int(item.elevation) if item.elevation else None
            gn.dem = int(item.dem) if item.dem else None
            gn.timezone = item.timezone or None
            gn.moddate = datetime.strptime(item.moddate, '%Y-%m-%d').date() if item.moddate else None

            gn.make_name()
            db.session.flush()  # Required for future make_name() calls to work correctly

    db.session.commit()


def load_alt_names(fd):
    progress = get_progressbar()
    print "Loading alternate names..."
    size = sum(1 for line in fd)
    fd.seek(0)  # Return to start
    loadprogress = ProgressBar(maxval=size,
        widgets=[progressbar.widgets.Percentage(), ' ', progressbar.widgets.Bar(), ' ', progressbar.widgets.ETA(), ' ']).start()

    def update_progress(counter):
        loadprogress.update(counter + 1)
        return True

    geonameids = set([r[0] for r in db.session.query(GeoName.id).all()])
    altnames = [GeoAltNameRecord(*row) for counter, row in enumerate(unicodecsv.reader(fd, delimiter='\t'))
        if update_progress(counter) and not row[0].startswith('#') and int(row[1]) in geonameids]

    loadprogress.finish()

    print "Processing %d records..." % len(altnames)
    GeoAltName.query.all()  # Load all data into session cache for faster lookup

    for item in progress(altnames):
        if item.geonameid:
            rec = GeoAltName.query.get(int(item.id))
            if rec is None:
                rec = GeoAltName()
                db.session.add(rec)
            rec.id = int(item.id)
            rec.geonameid = int(item.geonameid)
            rec.lang = item.lang or None
            rec.title = item.title
            rec.is_preferred_name = getbool(item.is_preferred_name) or False
            rec.is_short_name = getbool(item.is_short_name) or False
            rec.is_colloquial = getbool(item.is_colloquial) or False
            rec.is_historic = getbool(item.is_historic) or False

    db.session.commit()


def load_admin1_codes(fd):
    print "Loading admin1 codes..."
    progress = get_progressbar()
    admincodes = [GeoAdminRecord(*row) for row in unicodecsv.reader(fd, delimiter='\t')
        if not row[0].startswith('#')]

    GeoAdmin1Code.query.all()  # Load all data into session cache for faster lookup
    for item in progress(admincodes):
        if item.geonameid:
            rec = GeoAdmin1Code.query.get(item.geonameid)
            if rec is None:
                rec = GeoAdmin1Code()
                db.session.add(rec)
            rec.geonameid = item.geonameid
            rec.title = item.title
            rec.ascii_title = item.ascii_title
            rec.country_id, rec.admin1_code = item.code.split('.')

    db.session.commit()


def load_admin2_codes(fd):
    print "Loading admin2 codes..."
    progress = get_progressbar()
    admincodes = [GeoAdminRecord(*row) for row in unicodecsv.reader(fd, delimiter='\t')
        if not row[0].startswith('#')]

    GeoAdmin2Code.query.all()  # Load all data into session cache for faster lookup
    for item in progress(admincodes):
        if item.geonameid:
            rec = GeoAdmin2Code.query.get(item.geonameid)
            if rec is None:
                rec = GeoAdmin2Code()
                db.session.add(rec)
            rec.geonameid = int(item.geonameid)
            rec.title = item.title
            rec.ascii_title = item.ascii_title
            rec.country_id, rec.admin1_code, rec.admin2_code = item.code.split('.')

    db.session.commit()


def main(env):
    init_for(env)
    for filename in [
            'countryInfo.txt', 'admin1CodesASCII.txt', 'admin2Codes.txt',
            'IN.zip', 'allCountries.zip', 'alternateNames.zip']:
        downloadfile('http://download.geonames.org/export/dump/', filename)

    load_country_info(open('countryInfo.txt'))
    load_admin1_codes(open('admin1CodesASCII.txt'))
    load_admin2_codes(open('admin2Codes.txt'))
    load_geonames(open('IN.txt'))
    load_geonames(open('allCountries.txt'))
    load_alt_names(open('alternateNames.txt'))


if __name__ == '__main__':
    main(sys.argv[1])
